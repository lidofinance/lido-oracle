from threading import Thread

import pytest

from src.modules.csm.csm import CSOracle
from src.modules.performance.collector.collector import PerformanceCollector
from src.modules.submodules.types import FrameConfig
from src.utils.range import sequence
from src.web3py.types import Web3
from tests.fork.conftest import first_slot_of_epoch


@pytest.fixture()
def hash_consensus_bin():
    with open('tests/fork/contracts/csm/HashConsensus_bin', 'r') as f:
        yield f.read()


@pytest.fixture()
def csm_module(web3: Web3):
    yield CSOracle(web3)


@pytest.fixture()
def performance_local_db(testrun_path):
    from unittest.mock import patch
    from pathlib import Path
    from sqlmodel import create_engine
    from sqlalchemy import JSON
    from src.modules.performance.common.db import Duty

    def mock_get_database_url(self):
        db_path = Path(testrun_path) / "test_duties.db"
        return f"sqlite:///{db_path}"

    def mock_init(self):
        self.engine = create_engine(self._get_database_url(), echo=False)
        self._setup_database()

    table = Duty.__table__
    for col_name in ("attestations", "proposals_vids", "proposals_flags", "syncs_vids", "syncs_misses"):
        if col_name in table.c:
            table.c[col_name].type = JSON()

    with patch('src.modules.performance.common.db.DutiesDB._get_database_url', mock_get_database_url):
        with patch('src.modules.performance.common.db.DutiesDB.__init__', mock_init):
            yield


@pytest.fixture()
def performance_collector(performance_local_db, web3: Web3, frame_config: FrameConfig):
    yield PerformanceCollector(web3)


@pytest.fixture()
def performance_web_server(performance_local_db):
    from src.modules.performance.web.server import serve

    Thread(target=serve, daemon=True).start()
    yield


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
def missed_initial_frame(frame_config: FrameConfig, cycle_iterations):
    _from = frame_config.initial_epoch + frame_config.epochs_per_frame + 1
    _to = _from + cycle_iterations
    return [first_slot_of_epoch(i) for i in sequence(_from, _to)]


@pytest.mark.fork
@pytest.mark.parametrize(
    'module',
    [csm_module],
    indirect=True,
)
@pytest.mark.parametrize(
    'running_finalized_slots',
    [start_before_initial_epoch, start_after_initial_epoch, missed_initial_frame],
    indirect=True,
)
def test_csm_module_report(
    performance_web_server, performance_collector, module, set_oracle_members, running_finalized_slots, account_from
):
    assert module.report_contract.get_last_processing_ref_slot() == 0, "Last processing ref slot should be 0"
    members = set_oracle_members(count=2)

    report_frame = None
    to_distribute_before_report = module.w3.csm.fee_distributor.shares_to_distribute()

    switch_finalized, _ = running_finalized_slots
    # pylint:disable=duplicate-code
    while switch_finalized():
        performance_collector.cycle_handler()
        for _, private_key in members:
            # NOTE: reporters using the same cache
            with account_from(private_key):
                module.cycle_handler()
        report_frame = module.get_initial_or_current_frame(
            module._receive_last_finalized_slot()  # pylint: disable=protected-access
        )

    last_processing_after_report = module.w3.csm.oracle.get_last_processing_ref_slot()
    assert (
        last_processing_after_report == report_frame.ref_slot
    ), "Last processing ref slot should equal to initial ref slot"

    to_distribute_after_report = module.w3.csm.fee_distributor.shares_to_distribute()
    assert to_distribute_after_report < to_distribute_before_report, "Shares to distribute should decrease"

    nos_count = int(module.w3.csm.module.functions.getNodeOperatorsCount().call())
    assert to_distribute_after_report <= nos_count, "Dust after distribution should be less or equal to NOs count"
