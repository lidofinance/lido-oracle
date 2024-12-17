import subprocess

import pytest

from src import variables
from src.main import ipfs_providers
from src.modules.csm.csm import CSOracle
from src.providers.ipfs import MultiIPFSProvider, CID
from src.web3py.extensions import KeysAPIClientModule, LidoContracts, LidoValidatorsProvider, TransactionUtils, CSM
from tests.fork.conftest import first_slot_of_epoch


@pytest.fixture()
def mocked_ipfs_client(monkeypatch):
    def _publish(self, content: bytes, name: str | None = None) -> CID:
        return CID('Qm' + 'f' * 46)

    with monkeypatch.context():
        monkeypatch.setattr(MultiIPFSProvider, 'publish', _publish)
        ipfs = MultiIPFSProvider(ipfs_providers())
        yield ipfs


@pytest.fixture()
def hash_consensus_bin():
    with open('tests/fork/contracts/csm/HashConsensus_bin', 'r') as f:
        yield f.read()


@pytest.fixture()
def csm_extension(forked_web3):
    yield CSM(forked_web3)


@pytest.fixture()
def report_contract(csm_extension):
    yield csm_extension.oracle


@pytest.fixture()
def module(forked_web3, patched_cl_client, csm_extension, mocked_ipfs_client):
    kac = KeysAPIClientModule(variables.KEYS_API_URI, forked_web3)
    forked_web3.attach_modules(
        {
            'lido_contracts': LidoContracts,
            'lido_validators': LidoValidatorsProvider,
            'transaction': TransactionUtils,
            "csm": lambda: csm_extension,
            'cc': lambda: patched_cl_client,  # type: ignore[dict-item]
            'kac': lambda: kac,  # type: ignore[dict-item]
            "ipfs": lambda: mocked_ipfs_client,
        }
    )
    _module = CSOracle(forked_web3)
    yield _module
    subprocess.run(['rm', 'cache.pkl'])


@pytest.fixture
def start_before_initial_epoch(frame_config):
    _from = frame_config.initial_epoch - 2
    _to = frame_config.initial_epoch + 6
    return [first_slot_of_epoch(i) for i in range(_from, _to)]


@pytest.fixture
def start_after_initial_epoch(frame_config):
    _from = frame_config.initial_epoch + 2
    _to = frame_config.initial_epoch + 6
    return [first_slot_of_epoch(i) for i in range(_from, _to)]


@pytest.fixture
def missed_initial_frame(frame_config):
    _from = frame_config.initial_epoch + frame_config.epochs_per_frame + 1
    _to = _from + 6
    return [first_slot_of_epoch(i) for i in range(_from, _to)]


@pytest.mark.fork
@pytest.mark.parametrize(
    'running_finalized_slots',
    [start_before_initial_epoch, start_after_initial_epoch, missed_initial_frame],
    indirect=True,
)
def test_execute_module(
    running_finalized_slots,
    new_hash_consensus,
    set_oracle_members,
    module: CSOracle,
    account_from,
):
    assert module.report_contract.get_last_processing_ref_slot() == 0, "Last processing ref slot should be 0"
    members = set_oracle_members(count=2)

    report_frame = module.get_initial_or_current_frame(module._receive_last_finalized_slot())
    to_distribute_before_report = module.w3.csm.fee_distributor.shares_to_distribute()

    switch_finalized, current = running_finalized_slots
    while switch_finalized():
        for _, private_key in members:
            # NOTE: reporters using the same cache
            with account_from(private_key):
                module.cycle_handler()

    last_processing_after_report = module.w3.csm.oracle.get_last_processing_ref_slot()
    assert (
        last_processing_after_report == report_frame.ref_slot
    ), "Last processing ref slot should equal to initial ref slot"

    to_distribute_after_report = module.w3.csm.fee_distributor.shares_to_distribute()
    assert to_distribute_after_report < to_distribute_before_report, "Shares to distribute should decrease"

    nos_count = int(module.w3.csm.module.functions.getNodeOperatorsCount().call())
    assert to_distribute_after_report <= nos_count, "Dust after distribution should be less or equal to NOs count"
