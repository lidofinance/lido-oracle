import pytest

from src import variables
from src.modules.accounting.accounting import Accounting
from src.web3py.extensions import KeysAPIClientModule, LidoContracts, LidoValidatorsProvider, TransactionUtils
from tests.fork.conftest import first_slot_of_epoch


@pytest.fixture()
def module(forked_web3, patched_cl_client):
    kac = KeysAPIClientModule(variables.KEYS_API_URI, forked_web3)
    forked_web3.attach_modules(
        {
            'lido_contracts': LidoContracts,
            'lido_validators': LidoValidatorsProvider,
            'transaction': TransactionUtils,
            # "csm": lambda: csm_extension,
            'cc': lambda: patched_cl_client,  # type: ignore[dict-item]
            'kac': lambda: kac,  # type: ignore[dict-item]
            # "ipfs": lambda: _,
        }
    )
    _module = Accounting(forked_web3)
    yield _module


@pytest.fixture()
def report_contract(module):
    yield module.report_contract


@pytest.fixture()
def hash_consensus_bin():
    with open('tests/fork/contracts/accounting/HashConsensus_bin', 'r') as f:
        yield f.read()


@pytest.fixture
def start_before_initial_epoch(frame_config):
    _from = frame_config.initial_epoch - 1
    _to = frame_config.initial_epoch + 3
    return [first_slot_of_epoch(i) for i in range(_from, _to)]


@pytest.fixture
def start_after_initial_epoch(frame_config):
    _from = frame_config.initial_epoch + 1
    _to = frame_config.initial_epoch + 3
    return [first_slot_of_epoch(i) for i in range(_from, _to)]


@pytest.fixture
def missed_initial_frame(frame_config):
    _from = frame_config.initial_epoch + frame_config.epochs_per_frame + 1
    _to = _from + 3
    return [first_slot_of_epoch(i) for i in range(_from, _to)]


@pytest.mark.fork
@pytest.mark.parametrize(
    'running_finalized_slots',
    [start_before_initial_epoch, start_after_initial_epoch, missed_initial_frame],
    indirect=True,
)
def test_accounting_report(
    forked_web3, set_oracle_members, running_finalized_slots, account_from, module, new_hash_consensus
):
    assert module.report_contract.get_last_processing_ref_slot() == 0, "Last processing ref slot should be 0"
    members = set_oracle_members(count=2)

    report_frame = module.get_initial_or_current_frame(module._receive_last_finalized_slot())

    switch_finalized, current = running_finalized_slots
    while switch_finalized():
        for _, private_key in members:
            # NOTE: reporters using the same cache
            with account_from(private_key):
                module.cycle_handler()

    last_processing_after_report = module.report_contract.get_last_processing_ref_slot()
    assert (
        last_processing_after_report == report_frame.ref_slot
    ), "Last processing ref slot should equal to report ref slot"
