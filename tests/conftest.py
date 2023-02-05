from pathlib import Path

import pytest
from _pytest.fixtures import FixtureRequest
from web3 import Web3
from web3.providers import JSONBaseProvider

from src.variables import BEACON_NODE, WEB3_PROVIDER_URI
from src.web3_utils.typings import SlotNumber
from tests.mocks import chain_id_mainnet, eth_call_el_rewards_vault, eth_call_beacon_spec
from tests.providers import ResponseToFileProvider, ResponseFromFile, MockProvider, ResponseToFileBeaconChainClient, \
    ResponseFromFileBeaconChainClient


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
    provider = ResponseToFileProvider(WEB3_PROVIDER_URI)
    yield provider
    provider.save_responses(responses_path)


@pytest.fixture()
def response_to_file_bc_client(responses_path) -> ResponseToFileBeaconChainClient:
    client = ResponseToFileBeaconChainClient(BEACON_NODE)
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
    yield Web3(provider)


@pytest.fixture()
def beacon_client(request, responses_path):
    if request.config.getoption("--save-responses"):
        return request.getfixturevalue("response_to_file_bc_client")
    else:
        return ResponseFromFileBeaconChainClient(responses_path.with_suffix('.bc.json'))


@pytest.fixture(autouse=True)
def contracts(web3):
    from src.contracts import contracts
    contracts.initialize(web3)
    return contracts


@pytest.fixture()
def past_slot_and_block(provider):
    return SlotNumber(4595230), '0xc001b15307c51190fb653a885bc9c5003a7b9dacceb75825fa376fc68e1c1a62'
