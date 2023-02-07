from pathlib import Path

import pytest
from _pytest.fixtures import FixtureRequest
from src.web3_extentions.typings import Web3
from web3.providers import JSONBaseProvider

from src import variables
from src.typings import SlotNumber
from tests.mocks import chain_id_mainnet, eth_call_el_rewards_vault, eth_call_beacon_spec
from tests.providers import (
    ResponseToFileProvider,
    ResponseFromFile,
    MockProvider,
    ResponseToFileHTTPClient,
    ResponseFromFileHTTPClient,
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


@pytest.fixture()
def response_to_file_provider(responses_path) -> ResponseToFileProvider:
    provider = ResponseToFileProvider(variables.EXECUTION_CLIENT_URI)
    yield provider
    provider.save_responses(responses_path)


@pytest.fixture()
def response_to_file_bc_client(responses_path) -> ResponseToFileHTTPClient:
    client = ResponseToFileHTTPClient(variables.CONSENSUS_CLIENT_URI)
    yield client
    client.save_responses(responses_path.with_suffix('.bc.json'))


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

    yield Web3(provider, external_modules={
        'lido_contracts': LidoContracts,
        'transaction': TransactionUtils,
        'cc': lambda _w3: ConsensusClientModule(variables.CONSENSUS_CLIENT_URI, _w3),
        'kac': lambda _w3: KeysAPIClientModule(variables.KEYS_API_URI, _w3),
    })


@pytest.fixture()
def beacon_client(request, responses_path):
    if request.config.getoption("--save-responses"):
        return request.getfixturevalue("response_to_file_bc_client")
    else:
        return ResponseFromFileHTTPClient(responses_path.with_suffix('.bc.json'))


@pytest.fixture()
def past_slot_and_block(provider):
    return SlotNumber(4595230), '0xc001b15307c51190fb653a885bc9c5003a7b9dacceb75825fa376fc68e1c1a62'
