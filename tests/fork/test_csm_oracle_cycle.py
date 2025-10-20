import os
import subprocess
from pathlib import Path

import pytest

from src.modules.csm.csm import CSOracle
from src.modules.submodules.types import FrameConfig
from src.utils.range import sequence
from src.web3py.types import Web3
from tests.fork.conftest import first_slot_of_epoch, logger
from tests.fork.utils.lock import LockedDir


@pytest.fixture()
def hash_consensus_bin():
    with open('tests/fork/contracts/csm/HashConsensus_bin', 'r') as f:
        yield f.read()


@pytest.fixture(scope='session')
def csm_repo_path(testruns_folder_path):
    return Path(testruns_folder_path) / "community-staking-module"


@pytest.fixture(scope='session')
def prepared_csm_repo(testruns_folder_path, csm_repo_path):

    if os.environ.get("GITHUB_ACTIONS") == "true":
        # CI should have the repo cloned and prepared
        if os.path.exists(csm_repo_path):
            return csm_repo_path
        raise ValueError("No cloned community-staking-module repo found, but running in CI. Fix the workflow.")

    original_dir = os.getcwd()

    with LockedDir(testruns_folder_path):
        if not os.path.exists(csm_repo_path / ".prepared"):
            logger.info("TESTRUN Cloning community-staking-module repo")
            subprocess.run(
                ["git", "clone", "https://github.com/lidofinance/community-staking-module", csm_repo_path], check=True
            )
            os.chdir(csm_repo_path)
            subprocess.run(["git", "checkout", "develop"], check=True)
            subprocess.run(["just", "deps"], check=True)
            subprocess.run(["just", "build"], check=True)
            subprocess.run(["touch", ".prepared"], check=True)
            os.chdir(original_dir)

    return csm_repo_path


@pytest.fixture()
def csm_module(web3: Web3):
    yield CSOracle(web3)


@pytest.fixture
def start_before_initial_epoch(frame_config: FrameConfig):
    _from = frame_config.initial_epoch - 1
    _to = frame_config.initial_epoch + 4
    return [first_slot_of_epoch(i) for i in sequence(_from, _to)]


@pytest.fixture
def start_after_initial_epoch(frame_config: FrameConfig):
    _from = frame_config.initial_epoch + 1
    _to = frame_config.initial_epoch + 4
    return [first_slot_of_epoch(i) for i in sequence(_from, _to)]


@pytest.fixture
def missed_initial_frame(frame_config: FrameConfig):
    _from = frame_config.initial_epoch + frame_config.epochs_per_frame + 1
    _to = _from + 4
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
def test_csm_module_report(module, set_oracle_members, running_finalized_slots, account_from):
    assert module.report_contract.get_last_processing_ref_slot() == 0, "Last processing ref slot should be 0"
    members = set_oracle_members(count=2)

    report_frame = None
    to_distribute_before_report = module.w3.csm.fee_distributor.shares_to_distribute()

    switch_finalized, _ = running_finalized_slots
    # pylint:disable=duplicate-code
    while switch_finalized():
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
