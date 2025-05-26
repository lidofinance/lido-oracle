import pytest

from src.modules.accounting.accounting import Accounting
from src.modules.ejector.ejector import Ejector
from src.modules.submodules.types import FrameConfig
from src.utils.range import sequence
from tests.fork.conftest import first_slot_of_epoch


@pytest.fixture()
def hash_consensus_bin():
    with open('tests/fork/contracts/lido/HashConsensus_bin', 'r') as f:
        yield f.read()


@pytest.fixture
def accounting_module(web3):
    yield Accounting(web3)


@pytest.fixture
def ejector_module(web3):
    yield Ejector(web3)


@pytest.fixture
def start_before_initial_epoch(frame_config: FrameConfig):
    _from = frame_config.initial_epoch - 1
    _to = frame_config.initial_epoch + 2
    return [first_slot_of_epoch(i) for i in sequence(_from, _to)]


@pytest.fixture
def start_after_initial_epoch(frame_config: FrameConfig):
    _from = frame_config.initial_epoch + 1
    _to = frame_config.initial_epoch + 2
    return [first_slot_of_epoch(i) for i in sequence(_from, _to)]


@pytest.fixture
def missed_initial_frame(frame_config: FrameConfig):
    _from = frame_config.initial_epoch + frame_config.epochs_per_frame + 1
    _to = _from + 2
    return [first_slot_of_epoch(i) for i in sequence(_from, _to)]


@pytest.mark.fork
@pytest.mark.parametrize(
    'module',
    [accounting_module, ejector_module],
    indirect=True,
)
@pytest.mark.parametrize(
    'running_finalized_slots',
    [start_before_initial_epoch, start_after_initial_epoch, missed_initial_frame],
    indirect=True,
)
def test_lido_module_report(module, set_oracle_members, running_finalized_slots, account_from):
    # Skip if consensus version is different
    current_consensus_version = module.report_contract.get_consensus_version()
    if current_consensus_version != module.COMPATIBLE_CONSENSUS_VERSION:
        pytest.skip(
            f"Consensus version {current_consensus_version} does not match expected {module.COMPATIBLE_CONSENSUS_VERSION}"
        )

    assert module.report_contract.get_last_processing_ref_slot() == 0, "Last processing ref slot should be 0"
    members = set_oracle_members(count=2)

    report_frame = None

    switch_finalized, _ = running_finalized_slots
    while switch_finalized():
        for _, private_key in members:
            with account_from(private_key):
                module.cycle_handler()
        report_frame = module.get_initial_or_current_frame(
            module._receive_last_finalized_slot()  # pylint: disable=protected-access
        )

    last_processing_after_report = module.report_contract.get_last_processing_ref_slot()
    assert (
        last_processing_after_report == report_frame.ref_slot
    ), "Last processing ref slot should equal to report ref slot"
