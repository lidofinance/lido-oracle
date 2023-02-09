from pathlib import Path

import pytest
from _pytest.fixtures import FixtureRequest
from web3 import Web3
from web3.providers import JSONBaseProvider

from src.variables import CONSENSUS_CLIENT_URI, EXECUTION_CLIENT_URI, KEYS_API_URI
from src.typings import BlockStamp
from src.web3_extentions import LidoContracts, TransactionUtils, LidoValidatorsProvider
from tests.mocks import chain_id_mainnet, eth_call_el_rewards_vault, eth_call_beacon_spec
from tests.providers import (
    ResponseToFileProvider,
    ResponseFromFile,
    MockProvider,
    ResponseToFileConsensusClientModule,
    ResponseFromFileConsensusClientModule,
    ResponseToFileKeysAPIClientModule,
    ResponseFromFileKeysAPIClientModule,
)


def pytest_addoption(parser):
    parser.addoption(
        "--save-responses",
        action="store_true",
        default=False,
        help="Save responses from web3 providers",
    )


@pytest.fixture()
def responses_path(request: FixtureRequest) -> Path:
    return Path('tests/responses') / request.node.parent.name / (request.node.name + '.json')


# ----- Web3 Provider Mock -----
@pytest.fixture()
def response_to_file_provider(responses_path) -> ResponseToFileProvider:
    provider = ResponseToFileProvider(EXECUTION_CLIENT_URI)
    yield provider
    provider.save_responses(responses_path)


@pytest.fixture()
def mock_provider(responses_path) -> MockProvider:
    provider = MockProvider(fallback_provider=ResponseFromFile(responses_path))
    provider.add_mock(chain_id_mainnet)
    return provider


@pytest.fixture()
def provider(request, responses_path) -> JSONBaseProvider:
    if request.config.getoption("--save-responses"):
        return request.getfixturevalue("response_to_file_provider")
    else:
        return request.getfixturevalue("mock_provider")


@pytest.fixture()
def web3(provider) -> Web3:
    if isinstance(provider, MockProvider):
        provider.add_mocks(eth_call_el_rewards_vault, eth_call_beacon_spec)
    web3 = Web3(provider)

    yield web3


# ---- Consensus Client Mock ----
@pytest.fixture()
def response_to_file_cl_client(web3, responses_path) -> ResponseToFileConsensusClientModule:
    client = ResponseToFileConsensusClientModule(CONSENSUS_CLIENT_URI, web3)
    yield client
    client.save_responses(responses_path.with_suffix('.cl.json'))


@pytest.fixture()
def consensus_client(request, responses_path, web3):
    if request.config.getoption("--save-responses"):
        client = request.getfixturevalue("response_to_file_cl_client")
    else:
        client = ResponseFromFileConsensusClientModule(responses_path.with_suffix('.cl.json'), web3)
    web3.attach_modules({"cc": lambda: client})
    return client


# ---- Keys API Client Mock ----
@pytest.fixture()
def response_to_file_ka_client(web3, responses_path) -> ResponseToFileKeysAPIClientModule:
    client = ResponseToFileKeysAPIClientModule(KEYS_API_URI, web3)
    yield client
    client.save_responses(responses_path.with_suffix('.ka.json'))


@pytest.fixture()
def keys_api_client(request, responses_path, web3):
    if request.config.getoption("--save-responses"):
        client = request.getfixturevalue("response_to_file_ka_client")
    else:
        client = ResponseFromFileKeysAPIClientModule(responses_path.with_suffix('.ka.json'), web3)
    web3.attach_modules({"kac": lambda: client})
    return client


# ---- Lido contracts ----
@pytest.fixture()
def contracts(web3):
    web3.attach_modules({
        'lido_contracts': LidoContracts,
    })


# ---- Transaction Utils
@pytest.fixture()
def tx_utils(web3):
    web3.attach_modules({
        'transaction': TransactionUtils,
    })


# ---- Lido validators ----
@pytest.fixture()
def lido_validators(web3, consensus_client, keys_api_client):
    web3.attach_modules({
        'lido_validators': LidoValidatorsProvider,
    })


@pytest.fixture()
def past_blockstamp():
    yield BlockStamp(
        block_root='0xfc3a63409fe5c53c3bb06a96fc4caa89011452835f767e64bf59f2b6864037cc',
        state_root='0x7fcd917cbe34f306989c40bd64b8e2057a39dfbfda82025549f3a44e6b2295fc',
        slot_number=4947936,
        block_number=8457825,
        block_hash='0x0d61eeb26e4cbb076e557ddb8de092a05e2cba7d251ad4a87b0826cf5926f87b',
    )
