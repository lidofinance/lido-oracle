import json
import logging
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import cast, get_args

import pytest
import xdist
from _pytest.nodes import Item
from eth_account import Account
from faker.proxy import Faker
from web3 import Web3
from web3.types import RPCEndpoint
from web3_multi_provider import MultiProvider

from src import variables
from src.main import ipfs_providers
from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule
from src.modules.submodules.types import FrameConfig
from src.providers.consensus.client import ConsensusClient, LiteralState
from src.providers.consensus.types import BlockDetailsResponse, BlockRootResponse
from src.providers.execution.contracts.base_oracle import BaseOracleContract
from src.providers.execution.contracts.hash_consensus import HashConsensusContract
from src.providers.ipfs import CID
from src.types import BlockRoot, BlockStamp, SlotNumber
from src.utils.blockstamp import build_blockstamp
from src.utils.cache import clear_global_cache
from src.utils.slot import get_non_missed_slot_header
from src.variables import (
    HTTP_REQUEST_RETRY_COUNT_CONSENSUS,
    HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS,
    HTTP_REQUEST_TIMEOUT_CONSENSUS,
)
from src.web3py.contract_tweak import tweak_w3_contracts
from src.web3py.extensions import (
    IPFS,
    KeysAPIClientModule,
    LazyCSM,
    LidoContracts,
    LidoValidatorsProvider,
    TransactionUtils,
)

logger = logging.getLogger('fork_tests')

# pylint: disable=logging-fstring-interpolation


class TestRunningException(Exception):
    pass


@pytest.hookimpl(hookwrapper=True)
def pytest_collection_modifyitems(items: list[Item]):
    yield
    if any(not item.get_closest_marker("fork") for item in items):
        for item in items:
            if item.get_closest_marker("fork"):
                item.add_marker(
                    pytest.mark.skip(
                        reason="fork tests are take a lot of time and skipped if any other tests are selected"
                    )
                )


def pytest_sessionfinish(session, exitstatus):
    if xdist.is_xdist_worker(session):
        return
    subprocess.run(['rm', '-rf', './testruns'], check=True)


#
# Global
#


@pytest.fixture(autouse=True)
def clean_global_cache_after_test():
    yield
    logger.info("TESTRUN Clear global LRU functions cache (Autoused)")
    clear_global_cache()


@pytest.fixture(autouse=True)
def set_delay_and_sleep(monkeypatch):
    with monkeypatch.context():
        monkeypatch.setattr(
            variables,
            "SUBMIT_DATA_DELAY_IN_SLOTS",
            1,
        )
        monkeypatch.setattr(
            variables,
            "CYCLE_SLEEP_IN_SECONDS",
            1,
        )
        logger.info("TESTRUN Set SUBMIT_DATA_DELAY_IN_SLOTS and CYCLE_SLEEP_IN_SECONDS to 1")
        yield


@pytest.fixture(autouse=True)
def patch_csm_contract_load(monkeypatch):
    monkeypatch.setattr(
        "src.web3py.extensions.CSM.CONTRACT_LOAD_MAX_RETRIES",
        3,
    )
    monkeypatch.setattr(
        "src.web3py.extensions.CSM.CONTRACT_LOAD_RETRY_DELAY",
        0,
    )
    logger.info("TESTRUN Patched CSM CONTRACT_LOAD_MAX_RETRIES to 3 and CONTRACT_LOAD_RETRY_DELAY to 0")
    yield


@pytest.fixture(autouse=True)
def set_cache_path(monkeypatch, testrun_path):
    with monkeypatch.context():
        monkeypatch.setattr(
            variables,
            "CACHE_PATH",
            Path(testrun_path),
        )
        logger.info(f"TESTRUN Set CACHE_PATH to {testrun_path}")
        yield


@pytest.fixture(scope='session')
def testruns_folder_path():
    return Path("./testruns")


@pytest.fixture()
def testrun_path(testruns_folder_path, worker_id, testrun_uid):
    path = testruns_folder_path / f"{worker_id}_{testrun_uid}"
    subprocess.run(['mkdir', '-p', path], check=True)
    yield path
    subprocess.run(['rm', '-rf', path], check=True)


#
# Utils
#


@pytest.fixture
def account_from(monkeypatch):
    @contextmanager
    def _use(pk: str):
        with monkeypatch.context():
            monkeypatch.setattr(
                variables,
                "ACCOUNT",
                Account.from_key(private_key=pk),  # pylint: disable=no-value-for-parameter
            )
            logger.info(f"TESTRUN Switched to ACCOUNT {variables.ACCOUNT.address}")
            yield

    return _use


def first_slot_of_epoch(epoch: int) -> SlotNumber:
    return SlotNumber(epoch * 32 - 31)


#
# Common
#


@pytest.fixture
def real_cl_client():
    return ConsensusClient(
        variables.CONSENSUS_CLIENT_URI,
        HTTP_REQUEST_TIMEOUT_CONSENSUS,
        HTTP_REQUEST_RETRY_COUNT_CONSENSUS,
        HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS,
    )


@pytest.fixture
def real_finalized_slot(real_cl_client: ConsensusClient) -> SlotNumber:
    finalized_slot = real_cl_client.get_block_header('finalized').data.header.message.slot
    logger.info(f"TESTRUN True finalized slot on CL: {finalized_slot}")
    return finalized_slot


@pytest.fixture(params=[-24], ids=["initial epoch 24 epochs before real finalized epoch"])
def initial_epoch(request, real_finalized_slot: SlotNumber) -> int:
    return (real_finalized_slot // 32) + request.param


@pytest.fixture(params=[8], ids=["8 epochs per frame"])
def epochs_per_frame(request):
    return request.param


@pytest.fixture(params=[0], ids=["fast lane length 0"])
def fast_lane_length_slots(request):
    return request.param


@pytest.fixture
def frame_config(initial_epoch, epochs_per_frame, fast_lane_length_slots):
    _frame_config = FrameConfig(
        initial_epoch=initial_epoch,
        epochs_per_frame=epochs_per_frame,
        fast_lane_length_slots=fast_lane_length_slots,
    )
    logger.info(f"TESTRUN Frame config: {_frame_config}")
    return _frame_config


def get_next_non_missed_slot(
    cc: ConsensusClient,
    slot: SlotNumber,
    last_finalized_slot_number: SlotNumber,
) -> BlockDetailsResponse:
    """
    Get non-missed slot data. In case of missed slot, we take first next non-missed slot.
    """
    _, existing_header = get_non_missed_slot_header(cc, slot, last_finalized_slot_number)
    return cc.get_block_details(existing_header.data.root)


@pytest.fixture(params=[-4], ids=["fork 4 epochs before initial epoch"])
def blockstamp_for_forking(
    request, frame_config: FrameConfig, real_cl_client: ConsensusClient, real_finalized_slot: SlotNumber
) -> BlockStamp:
    slot_to_fork = first_slot_of_epoch(frame_config.initial_epoch + request.param)
    existing = get_next_non_missed_slot(
        real_cl_client,
        slot_to_fork,
        real_finalized_slot,
    )
    blockstamp = build_blockstamp(existing)
    logger.info(f"TESTRUN Blockstamp to fork: {blockstamp}")
    return blockstamp


@pytest.fixture()
def anvil_port():
    return Faker().random_int(min=10000, max=20000)


@pytest.fixture()
def forked_el_client(blockstamp_for_forking: BlockStamp, testrun_path: str, anvil_port: int):
    cli_params = [
        'anvil',
        '--port',
        str(anvil_port),
        '--config-out',
        f'{testrun_path}/localhost.json',
        '--auto-impersonate',
        '-f',
        variables.EXECUTION_CLIENT_URI[0],
        '--fork-block-number',
        str(blockstamp_for_forking.block_number),
    ]
    with subprocess.Popen(cli_params, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT) as process:
        time.sleep(5)
        logger.info(f"TESTRUN Started fork on {anvil_port=} from {blockstamp_for_forking.block_number=}")
        web3 = Web3(MultiProvider([f'http://127.0.0.1:{anvil_port}'], request_kwargs={'timeout': 5 * 60}))
        tweak_w3_contracts(web3)
        web3.provider.make_request(RPCEndpoint('anvil_setBlockTimestampInterval'), [12])
        web3.provider.make_request(RPCEndpoint('evm_setAutomine'), [True])
        # TODO: tx execution should somehow change corresponding block on CL
        yield web3
        process.terminate()
        process.wait()


@pytest.fixture()
def web3(forked_el_client, patched_cl_client, mocked_ipfs_client):
    kac = KeysAPIClientModule(variables.KEYS_API_URI, forked_el_client)
    forked_el_client.attach_modules(
        {
            'lido_contracts': LidoContracts,
            'lido_validators': LidoValidatorsProvider,
            'transaction': TransactionUtils,
            "csm": LazyCSM,  # type: ignore[dict-item]
            'cc': lambda: patched_cl_client,  # type: ignore[dict-item]
            'kac': lambda: kac,  # type: ignore[dict-item]
            "ipfs": lambda: mocked_ipfs_client,
        }
    )
    yield forked_el_client


@pytest.fixture()
def mocked_ipfs_client(monkeypatch, forked_el_client):
    def _publish(self, content: bytes, name: str | None = None) -> CID:
        return CID('Qm' + 'f' * 46)

    with monkeypatch.context():
        monkeypatch.setattr(IPFS, 'publish', _publish)
        ipfs = IPFS(forked_el_client, ipfs_providers())  # Web3 instance not needed for mocked publish
        yield ipfs


@pytest.fixture()
def accounts_from_fork(forked_el_client, testrun_path):
    with open(f'{testrun_path}/localhost.json') as f:
        data = json.load(f)
        addresses = data['available_accounts']
        private_keys = data['private_keys']
    return [forked_el_client.to_checksum_address(address) for address in addresses], private_keys


@pytest.fixture
def running_finalized_slots(request):
    slots = request.getfixturevalue(request.param.__name__)
    iterator = iter(slots)
    current = slots[0]
    logger.info(f"TESTRUN Running finalized slots: {slots}")

    def switch() -> SlotNumber | None:
        nonlocal current
        try:
            current = next(iterator)
        except StopIteration:
            current = None
        logger.info(f"TESTRUN Switched finalized to slot {current}")
        return current

    return switch, lambda: current


@pytest.fixture()
def patched_cl_client(monkeypatch, forked_el_client, real_cl_client, real_finalized_slot, running_finalized_slots):
    _, current = running_finalized_slots

    class PatchedConsensusClient(ConsensusClient):
        def get_block_root(self, state_id: SlotNumber | BlockRoot | LiteralState) -> BlockRootResponse:
            if state_id == 'genesis' or state_id not in get_args(LiteralState):
                return super().get_block_root(state_id)

            mocked_finalized_slot = current()
            if not mocked_finalized_slot:
                raise TestRunningException("Run out of running slots")

            slot_to_find = None

            if state_id == 'finalized':
                slot_to_find = mocked_finalized_slot

            if state_id == 'justified':
                # one epoch ahead of current slot
                possible_justified = SlotNumber(first_slot_of_epoch((mocked_finalized_slot // 32) + 1))
                slot_to_find = possible_justified

            if state_id == 'head':
                # two epochs ahead of current slot
                possible_head = SlotNumber(first_slot_of_epoch((mocked_finalized_slot // 32) + 2))
                slot_to_find = possible_head

            if slot_to_find is None:
                raise TestRunningException(f"Unknown state_id: {state_id}")

            existing = get_next_non_missed_slot(
                self,
                slot_to_find,
                real_finalized_slot,
            ).message.slot

            return self.get_block_root(existing)

        def get_block_details(self, state_id: SlotNumber | BlockRoot) -> BlockDetailsResponse:
            """
            Method to get patched CL block details with EL data from forked client
            """
            slot_details = super().get_block_details(state_id)
            block_from_fork = None
            while not block_from_fork:
                try:
                    block_from_fork = forked_el_client.eth.get_block(
                        slot_details.message.body.execution_payload.block_number
                    )
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.debug(f"TESTRUN FORKED CLIENT: {e}")
                if not block_from_fork:
                    latest_el = int(forked_el_client.eth.get_block('latest')['number'])
                    from_cl = slot_details.message.body.execution_payload.block_number
                    diff = from_cl - latest_el
                    if diff < 0:
                        raise TestRunningException(f"TESTRUN Latest block {latest_el} is ahead block {from_cl}")
                    for _ in range(diff):
                        forked_el_client.provider.make_request(RPCEndpoint('evm_mine'), [])
                        time.sleep(0.2)

            slot_details.message.body.execution_payload.block_number = block_from_fork['number']
            slot_details.message.body.execution_payload.block_hash = block_from_fork['hash'].hex()
            slot_details.message.body.execution_payload.timestamp = block_from_fork['timestamp']
            return slot_details

    yield PatchedConsensusClient(
        variables.CONSENSUS_CLIENT_URI,
        HTTP_REQUEST_TIMEOUT_CONSENSUS,
        HTTP_REQUEST_RETRY_COUNT_CONSENSUS,
        HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS,
    )


@pytest.fixture()
def module(request) -> BaseModule | ConsensusModule:
    module = request.getfixturevalue(request.param.__name__)
    yield module


@pytest.fixture()
def report_contract(module):
    yield module.report_contract


@pytest.fixture()
def hash_consensus_bin():
    raise TestRunningException("TESTRUN `hash_consensus_bin` fixture should be overriden on tests level")


@pytest.fixture()
def new_hash_consensus(  # pylint: disable=too-many-positional-arguments
    forked_el_client,
    real_cl_client,
    frame_config,
    accounts_from_fork,
    report_contract: BaseOracleContract,
    hash_consensus_bin,
):
    addresses, _ = accounts_from_fork
    admin, *_ = addresses

    HashConsensus = forked_el_client.eth.contract(
        ContractFactoryClass=HashConsensusContract, bytecode=hash_consensus_bin
    )
    new_consensus_address = forked_el_client.eth.wait_for_transaction_receipt(
        HashConsensus.constructor(
            slotsPerEpoch=32,
            secondsPerSlot=12,
            genesisTime=real_cl_client.get_genesis().genesis_time,
            epochsPerFrame=frame_config.epochs_per_frame,
            fastLaneLengthSlots=frame_config.fast_lane_length_slots,
            admin=admin,
            reportProcessor=report_contract.address,
        ).transact({'from': admin})
    ).contractAddress

    new_consensus = cast(
        HashConsensusContract,
        forked_el_client.eth.contract(
            address=new_consensus_address, ContractFactoryClass=HashConsensusContract, decode_tuples=True
        ),
    )

    DEFAULT_ADMIN_ROLE = "0x" + new_consensus.functions.DEFAULT_ADMIN_ROLE().call().hex()
    default_admin = new_consensus.functions.getRoleMember(bytes(32), 0).call()
    new_consensus.functions.updateInitialEpoch(frame_config.initial_epoch).transact({'from': default_admin})

    oracle_admin = report_contract.functions.getRoleMember(DEFAULT_ADMIN_ROLE, 0).call()
    forked_el_client.provider.make_request('anvil_setBalance', [oracle_admin, hex(10**18)])

    MANAGE_CONSENSUS_CONTRACT_ROLE = "0x" + report_contract.functions.MANAGE_CONSENSUS_CONTRACT_ROLE().call().hex()
    report_contract.functions.grantRole(MANAGE_CONSENSUS_CONTRACT_ROLE, admin).transact({'from': oracle_admin})
    report_contract.functions.setConsensusContract(new_consensus_address).transact({'from': admin})

    storage_slot = forked_el_client.keccak(text="lido.BaseOracle.lastProcessingRefSlot")
    forked_el_client.provider.make_request('anvil_setStorageAt', [report_contract.address, storage_slot, bytes(32)])

    yield new_consensus


@pytest.fixture()
def set_oracle_members(new_hash_consensus: HashConsensusContract, accounts_from_fork):
    addresses, private_keys = accounts_from_fork

    def _set_members(count: int = 2):
        DEFAULT_ADMIN_ROLE = "0x" + new_hash_consensus.functions.DEFAULT_ADMIN_ROLE().call().hex()
        MANAGE_MEMBERS_AND_QUORUM_ROLE = (
            "0x" + new_hash_consensus.functions.MANAGE_MEMBERS_AND_QUORUM_ROLE().call().hex()
        )

        admin = new_hash_consensus.functions.getRoleMember(DEFAULT_ADMIN_ROLE, 0).call()
        new_hash_consensus.functions.grantRole(MANAGE_MEMBERS_AND_QUORUM_ROLE, admin).transact({'from': admin})

        for address in addresses[:count]:
            current_quorum = new_hash_consensus.functions.getQuorum().call()
            new_hash_consensus.functions.addMember(address, current_quorum + 1).transact({'from': admin})

        return [(addresses[i], private_keys[i]) for i in range(count)]

    return _set_members
