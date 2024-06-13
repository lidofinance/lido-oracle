from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock

import pytest
from _pytest.fixtures import FixtureRequest
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from web3.middleware import construct_simple_cache_middleware
from web3.types import Timestamp

import src.variables
from src.types import BlockNumber, EpochNumber, ReferenceBlockStamp, SlotNumber
from src.variables import CONSENSUS_CLIENT_URI, EXECUTION_CLIENT_URI, KEYS_API_URI
from src.web3py.contract_tweak import tweak_w3_contracts
from src.web3py.extensions import LidoContracts, LidoValidatorsProvider, TransactionUtils
from src.web3py.types import Web3
from tests.providers import (
    ResponseFromFile,
    ResponseFromFileConsensusClientModule,
    ResponseFromFileKeysAPIClientModule,
    UpdateResponsesConsensusClientModule,
    UpdateResponsesKeysAPIClientModule,
    UpdateResponsesProvider,
)


def pytest_addoption(parser):
    parser.addoption(
        "--update-responses",
        action="store_true",
        default=False,
        help="Update responses from web3 providers. "
        "New responses will be added to the files, unused responses will be removed.",
    )


@pytest.fixture()
def responses_path(request: FixtureRequest) -> Path:
    return Path(request.node.parent.name) / (request.node.name + '.json')


# ----- Web3 Provider Mock -----
@pytest.fixture()
def update_responses_provider(responses_path) -> UpdateResponsesProvider:
    provider = UpdateResponsesProvider(responses_path, EXECUTION_CLIENT_URI)
    yield provider
    provider.save_responses(responses_path)


@pytest.fixture()
def mock_provider(responses_path) -> ResponseFromFile:
    provider = ResponseFromFile(responses_path)
    return provider


@pytest.fixture()
def provider(request, responses_path) -> UpdateResponsesProvider | ResponseFromFile:
    if request.config.getoption("--update-responses"):
        return request.getfixturevalue("update_responses_provider")

    return request.getfixturevalue("mock_provider")


@pytest.fixture()
def web3(provider) -> Web3:
    web3 = Web3(provider)
    tweak_w3_contracts(web3)
    web3.middleware_onion.add(construct_simple_cache_middleware())

    with provider.use_mock(Path('common/chainId.json')):
        _ = web3.eth.chain_id
    yield web3


# ---- Consensus Client Mock ----
@pytest.fixture()
def update_responses_cl_client(web3, responses_path) -> UpdateResponsesConsensusClientModule:
    path = responses_path.with_suffix('.cl.json')
    client = UpdateResponsesConsensusClientModule(path, CONSENSUS_CLIENT_URI, web3)
    yield client
    client.save_responses(path)


@pytest.fixture()
def consensus_client(request, responses_path, web3):
    if request.config.getoption("--update-responses"):
        client = request.getfixturevalue("update_responses_cl_client")
    else:
        client = ResponseFromFileConsensusClientModule(responses_path.with_suffix('.cl.json'), web3)
    web3.attach_modules({"cc": lambda: client})


# ---- Keys API Client Mock ----
@pytest.fixture()
def update_responses_ka_client(web3, responses_path) -> UpdateResponsesKeysAPIClientModule:
    path = responses_path.with_suffix('.ka.json')
    client = UpdateResponsesKeysAPIClientModule(path, KEYS_API_URI, web3)
    yield client
    client.save_responses(path)


@pytest.fixture()
def keys_api_client(request, responses_path, web3):
    if request.config.getoption("--update-responses"):
        client = request.getfixturevalue("update_responses_ka_client")
    else:
        client = ResponseFromFileKeysAPIClientModule(responses_path.with_suffix('.ka.json'), web3)
    web3.attach_modules({"kac": lambda: client})


@pytest.fixture()
def csm(web3):
    mock = Mock()
    web3.attach_modules({"csm": lambda: mock})
    return mock


# ---- Lido contracts ----
@pytest.fixture()
def contracts(web3, provider):
    src.variables.LIDO_LOCATOR_ADDRESS = "0x548C1ED5C83Bdf19e567F4cd7Dd9AC4097088589"
    LidoContracts._check_contracts = Mock()  # pylint: disable=protected-access
    with provider.use_mock(Path('common/contracts.json')):
        # First contracts deployment
        web3.attach_modules(
            {
                'lido_contracts': LidoContracts,
            }
        )


# ---- Transaction Utils
@pytest.fixture()
def tx_utils(web3):
    web3.attach_modules(
        {
            'transaction': TransactionUtils,
        }
    )


# ---- Lido validators ----
@pytest.fixture()
def lido_validators(web3, consensus_client, keys_api_client):
    web3.attach_modules(
        {
            'lido_validators': LidoValidatorsProvider,
        }
    )


def get_blockstamp_by_state(w3, state_id) -> ReferenceBlockStamp:
    root = w3.cc.get_block_root(state_id).root
    slot_details = w3.cc.get_block_details(root)

    return ReferenceBlockStamp(
        slot_number=SlotNumber(int(slot_details.message.slot)),
        state_root=slot_details.message.state_root,
        block_number=BlockNumber(int(slot_details.message.body.execution_payload.block_number)),
        block_hash=slot_details.message.body.execution_payload.block_hash,
        block_timestamp=Timestamp(slot_details.message.body.execution_payload.timestamp),
        ref_slot=SlotNumber(int(slot_details.message.slot)),
        ref_epoch=EpochNumber(int(int(slot_details.message.slot) / 12)),
    )


@dataclass
class Account:
    address: ChecksumAddress
    _private_key: HexBytes
