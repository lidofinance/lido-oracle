import subprocess
import time
import json
from dataclasses import dataclass
from typing import cast

from eth_account import Account
import pytest
from eth_abi.packed import encode_packed
from web3 import Web3
from web3.middleware import construct_simple_cache_middleware
from web3_multi_provider import MultiProvider

from src import variables
from src.main import ipfs_providers
from src.modules.csm.checkpoint import FrameCheckpointsIterator
from src.modules.csm.csm import CSOracle, logger
from src.modules.submodules.oracle_module import ModuleExecuteDelay
from src.providers.consensus.client import ConsensusClient, LiteralState
from src.providers.consensus.types import BlockDetailsResponse, BlockRootResponse
from src.providers.execution.contracts.hash_consensus import HashConsensusContract
from src.providers.ipfs import MultiIPFSProvider, CID
from src.types import BlockRoot, SlotNumber
from src.utils.blockstamp import build_blockstamp
from src.variables import (
    HTTP_REQUEST_TIMEOUT_CONSENSUS,
    HTTP_REQUEST_RETRY_COUNT_CONSENSUS,
    HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS,
)
from src.web3py.contract_tweak import tweak_w3_contracts
from src.web3py.extensions import (
    CSM,
    LidoContracts,
    LidoValidatorsProvider,
    TransactionUtils,
    ConsensusClientModule,
    KeysAPIClientModule,
)


@dataclass
class FrameConfig:
    fast_lane: int
    frame_size: int
    initial_epoch: int


frame_config = FrameConfig(
    fast_lane=0,
    frame_size=10,
    initial_epoch=322715,
)


@pytest.fixture
def running_slots(request):
    slots = request.param
    iterator = iter(slots)
    current = slots[0]

    def get_current() -> SlotNumber | None:
        nonlocal current
        return current

    def get_next() -> SlotNumber | None:
        nonlocal current
        try:
            current = next(iterator)
        except StopIteration:
            current = None
        return current

    return get_next, get_current


@pytest.fixture()
def adjust_min_checkpoint_step(monkeypatch):
    with monkeypatch.context():
        monkeypatch.setattr(
            FrameCheckpointsIterator,
            "MIN_CHECKPOINT_STEP",
            0,
        )
        yield


@pytest.fixture()
def pure_cl_client():
    yield ConsensusClient(
        variables.CONSENSUS_CLIENT_URI,
        HTTP_REQUEST_TIMEOUT_CONSENSUS,
        HTTP_REQUEST_RETRY_COUNT_CONSENSUS,
        HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS,
    )


@pytest.fixture()
def el_block_number_to_fork(request, pure_cl_client):
    slot_for_fork = request.param
    if not slot_for_fork:
        raise ValueError("Slot for fork is not set in test parameters")
    logger.info(f"Getting block number to fork from slot {slot_for_fork}")
    block_details = pure_cl_client.get_block_details(slot_for_fork)
    return int(block_details.message.body.execution_payload.block_number)


@pytest.fixture()
def run_fork(el_block_number_to_fork):
    cli_params = [
        'anvil',
        '--config-out',
        'localhost.json',
        '--auto-impersonate',
        '-f',
        variables.EXECUTION_CLIENT_URI[0],
        '--fork-block-number',
        str(el_block_number_to_fork),
    ]
    process = subprocess.Popen(cli_params, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(5)
    logger.info(f"Started fork from block {el_block_number_to_fork}")
    yield process
    process.terminate()
    process.wait()
    subprocess.run(['rm', 'localhost.json'])


@pytest.fixture()
def provider(run_fork):
    yield MultiProvider(['http://127.0.0.1:8545'], request_kwargs={'timeout': variables.HTTP_REQUEST_TIMEOUT_EXECUTION})


@pytest.fixture()
def web3(provider) -> Web3:
    web3 = Web3(provider)
    tweak_w3_contracts(web3)
    web3.middleware_onion.add(construct_simple_cache_middleware())
    web3.provider.make_request('anvil_setBlockTimestampInterval', [12])
    yield web3


@pytest.fixture()
def fork_account(monkeypatch, web3):
    with open('localhost.json') as f:
        data = json.load(f)
        address = data['available_accounts'][0]
        private_key = data['private_keys'][0]
    return web3.to_checksum_address(address), private_key


@pytest.fixture()
def set_account_from_fork(monkeypatch, fork_account):
    _, private_key = fork_account
    with monkeypatch.context():
        monkeypatch.setattr(
            variables,
            "ACCOUNT",
            Account.from_key(private_key),
        )
        yield


@pytest.fixture()
def consensus(web3):
    consensus = cast(
        HashConsensusContract,
        web3.eth.contract(
            # TODO: get from somewhere
            address=web3.to_checksum_address("0x71093efF8D8599b5fA340D665Ad60fA7C80688e4"),
            ContractFactoryClass=HashConsensusContract,
            decode_tuples=True,
        ),
    )
    yield consensus


@pytest.fixture()
def set_frame_config(request, web3, consensus):
    if not request.param:
        raise ValueError("Frame config is not set in test parameters")
    frame_config_tuple = (request.param.fast_lane, request.param.frame_size, request.param.initial_epoch)
    encoded = encode_packed(('uint64', 'uint64', 'uint64'), frame_config_tuple).rjust(32, b'\0')
    web3.provider.make_request('anvil_setStorageAt', [consensus.address, hex(0), '0x' + encoded.hex()])


@pytest.fixture()
def use_fork_account_as_reporter(web3, consensus, set_account_from_fork, fork_account):

    DEFAULT_ADMIN_ROLE = "0x" + consensus.functions.DEFAULT_ADMIN_ROLE().call().hex()
    MANAGE_MEMBERS_AND_QUORUM_ROLE = "0x" + consensus.functions.MANAGE_MEMBERS_AND_QUORUM_ROLE().call().hex()

    hash_consensus_admin = consensus.functions.getRoleMember(DEFAULT_ADMIN_ROLE, 0).call()

    web3.provider.make_request('anvil_setBalance', [hash_consensus_admin, hex(10**18)])

    address, _ = fork_account

    tx_grant_role = consensus.functions.grantRole(DEFAULT_ADMIN_ROLE, address)
    web3.eth.send_transaction(tx_grant_role.build_transaction({'from': hash_consensus_admin}))

    tx_grant_role = consensus.functions.grantRole(MANAGE_MEMBERS_AND_QUORUM_ROLE, address)
    web3.eth.send_transaction(tx_grant_role.build_transaction({'from': address}))

    current_quorum = consensus.functions.getQuorum().call()
    tx_add_member = consensus.functions.addMember(address, current_quorum + 1)
    web3.eth.send_transaction(tx_add_member.build_transaction({'from': address}))


@pytest.fixture()
def adjust_cl_client(monkeypatch, web3, running_slots):

    get_next, get_current = running_slots

    def get_block_root(self, state_id: SlotNumber | BlockRoot | LiteralState) -> BlockRootResponse:
        """
        Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockRoot

        There is no cache because this method is used to get finalized and head blocks.
        """

        def _inner(_state_id: SlotNumber | BlockRoot | LiteralState):
            data, _ = self._get(
                self.API_GET_BLOCK_ROOT,
                path_params=(_state_id,),
            )
            if not isinstance(data, dict):
                raise ValueError("Expected mapping response from getBlockRoot")
            return BlockRootResponse.from_response(**data)

        if state_id not in ['head', 'genesis', 'finalized', 'justified']:
            return _inner(state_id)

        if state_id == 'finalized':
            current = get_current()
            if not current:
                raise ValueError("No current running slot number available")
            return _inner(current)

        if state_id == 'head':
            current = get_current()
            if not current:
                raise ValueError("No current running slot number available")
            latest = (((current * 32) + 1) // 32) + 32
            return _inner(SlotNumber(latest))

        raise ValueError(f"Unknown state_id for patching: {state_id}")

    def get_block_details(self, state_id: SlotNumber | BlockRoot) -> BlockDetailsResponse:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockV2"""
        data, _ = self._get(
            self.API_GET_BLOCK_DETAILS,
            path_params=(state_id,),
        )
        if not isinstance(data, dict):
            raise ValueError("Expected mapping response from getBlockV2")
        slot_details = BlockDetailsResponse.from_response(**data)
        block_from_fork = None
        while not block_from_fork:
            try:
                block_from_fork = web3.eth.get_block(int(slot_details.message.body.execution_payload.block_number))
            except Exception as e:
                logger.error(f"Failed to get block from fork: {e}")
            if not block_from_fork:
                latest = web3.eth.get_block('latest')
                diff = int(slot_details.message.body.execution_payload.block_number) - int(latest['number'])
                for _ in range(diff):
                    web3.provider.make_request('evm_mine', [])
                    logger.info(f"Mined block {web3.eth.block_number}")
        slot_details.message.body.execution_payload.block_number = block_from_fork['number']
        slot_details.message.body.execution_payload.block_hash = block_from_fork['hash'].hex()
        slot_details.message.body.execution_payload.timestamp = block_from_fork['timestamp']
        return slot_details

    with monkeypatch.context():
        monkeypatch.setattr(
            ConsensusClient,
            "get_block_details",
            get_block_details,
        )
        monkeypatch.setattr(
            ConsensusClient,
            "get_block_root",
            get_block_root,
        )
        yield


@pytest.fixture()
def adjust_ipfs_client(monkeypatch):
    def _publish(self, content: bytes, name: str | None = None) -> CID:
        return CID('Qm' + 'f' * 46)

    with monkeypatch.context():
        monkeypatch.setattr(
            MultiIPFSProvider,
            "publish",
            _publish,
        )
        yield


@pytest.fixture()
def module(web3, adjust_ipfs_client, adjust_cl_client, adjust_min_checkpoint_step):
    cc = ConsensusClientModule(variables.CONSENSUS_CLIENT_URI, web3)
    kac = KeysAPIClientModule(variables.KEYS_API_URI, web3)
    ipfs = MultiIPFSProvider(ipfs_providers())
    web3.attach_modules(
        {
            'lido_contracts': LidoContracts,
            'lido_validators': LidoValidatorsProvider,
            'transaction': TransactionUtils,
            'cc': lambda: cc,  # type: ignore[dict-item]
            'kac': lambda: kac,  # type: ignore[dict-item]
            "ipfs": lambda: ipfs,
            "csm": CSM,
        }
    )
    _module = CSOracle(web3)
    yield _module
    subprocess.run(['rm', 'cache.pkl'])


def first_slot_of_epoch(epoch: int) -> SlotNumber:
    return SlotNumber(epoch * 32 - 31)


@pytest.mark.mainnet_fork
@pytest.mark.parametrize(
    'el_block_number_to_fork', [SlotNumber((frame_config.initial_epoch - 1) * 32 - 31)], indirect=True
)
@pytest.mark.parametrize('set_frame_config', [frame_config], indirect=True)
@pytest.mark.parametrize(
    'running_slots',
    [
        [first_slot_of_epoch(i) for i in range(frame_config.initial_epoch - 1, frame_config.initial_epoch + 4)],
        [first_slot_of_epoch(i) for i in range(frame_config.initial_epoch + 1, frame_config.initial_epoch + 4)],
    ],
    ids=['start_before_initial_epoch', 'start_after_initial_epoch'],
    indirect=True,
)
def test_execute_module(
    el_block_number_to_fork,
    set_frame_config,
    set_account_from_fork,
    use_fork_account_as_reporter,
    running_slots,
    module: CSOracle,
):
    delay = -1

    get_next, _ = running_slots

    while sn := get_next():
        block_root = BlockRoot(module.w3.cc.get_block_root(sn).root)
        block_details = module.w3.cc.get_block_details(block_root)
        bs = build_blockstamp(block_details)

        delay = module.execute_module(last_finalized_blockstamp=bs)

    assert delay == ModuleExecuteDelay.NEXT_SLOT
    # TODO: check that report was published
