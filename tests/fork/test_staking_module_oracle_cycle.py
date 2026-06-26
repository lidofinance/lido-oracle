import time
from pathlib import Path
from threading import Thread
from unittest.mock import patch

import pytest
import uvicorn
from faker import Faker
from sqlalchemy import JSON
from sqlalchemy.pool import NullPool
from sqlmodel import create_engine

from src.modules.common.types import FrameConfig
from src.modules.oracles.staking_modules.community_staking.csm import CSPerformanceOracle
from src.modules.oracles.staking_modules.curated.cm import CMPerformanceOracle
from src.modules.sidecars.performance.collector.collector import PerformanceCollector
from src.modules.sidecars.performance.common.db import Duty
from src.modules.sidecars.performance.web.server import app
from src.utils.range import sequence
from src.web3py.extensions import PerformanceClientModule
from src.web3py.types import Web3Base, Web3StakingModule
from tests.fork.conftest import first_slot_of_epoch


# pylint: disable=protected-access


@pytest.fixture()
def hash_consensus_bin():
    with open('tests/fork/contracts/csm/HashConsensus_bin') as f:
        yield f.read()


@pytest.fixture()
def csm_module(web3_cs_module: Web3StakingModule):
    yield CSPerformanceOracle(web3_cs_module)


@pytest.fixture()
def cm_module(web3_curated_module: Web3StakingModule):
    yield CMPerformanceOracle(web3_curated_module)


@pytest.fixture()
def performance_local_db(testrun_path):
    db_path = (Path(testrun_path) / "test_duties.db").resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.touch(mode=0o600, exist_ok=True)

    def mock_get_database_url(self):
        return f"sqlite:///{db_path}"

    def mock_build_engine(self, connect_timeout):
        return create_engine(
            self._get_database_url(),
            echo=False,
            connect_args={"check_same_thread": False, "timeout": 30},
            poolclass=NullPool,
        )

    def mock_init(self, *args, **kwargs):
        self._statement_timeout_ms = kwargs.get('statement_timeout_ms')
        self.engine = self._build_engine(kwargs.get('connect_timeout'))
        self._setup_database()

    table = Duty.__table__
    for col_name in ("missed_attestation_vids", "proposals_vids", "proposals_flags", "syncs_vids", "syncs_misses"):
        if col_name in table.c:
            table.c[col_name].type = JSON()

    with (
        patch('src.modules.sidecars.performance.common.db.DutiesDB._get_database_url', mock_get_database_url),
        patch('src.modules.sidecars.performance.common.db.DutiesDB._build_engine', mock_build_engine),
        patch('src.modules.sidecars.performance.common.db.DutiesDB.__init__', mock_init),
    ):
        yield mock_get_database_url, mock_init


@pytest.fixture()
def performance_collector(performance_local_db, web3: Web3Base, frame_config: FrameConfig):
    yield PerformanceCollector(web3.cc)


@pytest.fixture()
def performance_web_server_port():
    return Faker().random_int(min=10000, max=20000)


@pytest.fixture()
def performance_web_server(performance_local_db, web3: Web3Base, performance_web_server_port):
    config = uvicorn.Config(app, host='127.0.0.1', port=performance_web_server_port, log_level='error')
    server = uvicorn.Server(config)
    thread = Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)

    performance = PerformanceClientModule([f"http://127.0.0.1:{performance_web_server_port}"])
    web3.attach_modules({'performance': lambda: performance})

    yield
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def cycle_iterations():
    return 4


@pytest.fixture
def start_before_initial_epoch(frame_config: FrameConfig, cycle_iterations):
    _from = frame_config.initial_epoch - 1
    _to = frame_config.initial_epoch + cycle_iterations
    return [first_slot_of_epoch(i) for i in sequence(_from, _to)]


@pytest.fixture
def start_after_initial_epoch(frame_config: FrameConfig, cycle_iterations):
    _from = frame_config.initial_epoch + 1
    _to = frame_config.initial_epoch + cycle_iterations
    return [first_slot_of_epoch(i) for i in sequence(_from, _to)]


@pytest.fixture
def start_after_initial_frame(frame_config: FrameConfig, cycle_iterations):
    _from = frame_config.initial_epoch + frame_config.epochs_per_frame + 1
    _to = _from + cycle_iterations
    return [first_slot_of_epoch(i) for i in sequence(_from, _to)]


@pytest.fixture
def frame_index_as_processed(request):
    # None means no frame was processed yet
    return request.param


@pytest.mark.fork
@pytest.mark.integration
@pytest.mark.parametrize(
    'module',
    [
        csm_module,
        # cm_module # TODO: uncomment when Curated Module is ready on Mainnet
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    'running_finalized_slots,frame_index_as_processed',
    [
        (start_before_initial_epoch, None),
        (start_after_initial_epoch, None),
        (start_after_initial_frame, None),
        (start_after_initial_frame, 0),
    ],
    indirect=True,
)
def test_staking_module_module_report(
    performance_web_server,
    performance_collector,
    module,
    set_oracle_members,
    process_frame_index,
    running_finalized_slots,
    frame_index_as_processed,
    account_from,
):
    current_contract_version = module.report_contract.get_contract_version('latest')
    if current_contract_version != module.COMPATIBLE_CONTRACT_VERSION:
        pytest.skip(
            f"Contract version {current_contract_version} does not match expected {module.COMPATIBLE_CONTRACT_VERSION}"
        )

    current_consensus_version = module.report_contract.get_consensus_version('latest')
    if current_consensus_version != module.COMPATIBLE_CONSENSUS_VERSION:
        pytest.skip(
            f"Consensus version {current_consensus_version} does not match expected "
            f"{module.COMPATIBLE_CONSENSUS_VERSION}"
        )

    assert module.report_contract.get_last_processing_ref_slot('latest') == 0, "Last processing ref slot should be 0"
    if frame_index_as_processed is not None:
        process_frame_index(frame_index_as_processed)

    members = set_oracle_members(count=2)

    report_frame = None
    to_distribute_before_report = module.w3.staking_module.fee_distributor.shares_to_distribute('latest')

    switch_finalized, _ = running_finalized_slots
    # pylint:disable=duplicate-code
    while switch_finalized():
        performance_collector.cycle_handler()
        for _, private_key in members:
            # NOTE: reporters using the same cache
            with account_from(private_key):
                module.cycle_handler()
        _block = module._receive_last_finalized_block()  # pylint: disable=protected-access
        _bs = module._blockstamp_builder.build_blockstamp(_block)  # pylint: disable=protected-access
        report_frame = module.get_initial_or_current_frame(_bs)

    last_processing_after_report = module.w3.staking_module.oracle.get_last_processing_ref_slot('latest')
    assert last_processing_after_report == report_frame.ref_slot, (
        "Last processing ref slot should equal to initial ref slot"
    )

    # When the test is running after the real report,
    # but no new shares were distributed on module by Staking Router yet.
    if to_distribute_before_report == 0:
        return

    to_distribute_after_report = module.w3.staking_module.fee_distributor.shares_to_distribute('latest')
    assert to_distribute_after_report < to_distribute_before_report, "Shares to distribute should decrease"

    nos_count = int(module.w3.staking_module.module.functions.getNodeOperatorsCount().call())
    assert to_distribute_after_report <= nos_count, "Dust after distribution should be less or equal to NOs count"
