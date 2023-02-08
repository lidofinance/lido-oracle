from pathlib import Path

import pytest
from _pytest.fixtures import FixtureRequest
from web3 import Web3
from web3.providers import JSONBaseProvider

from src.variables import CONSENSUS_CLIENT_URI, EXECUTION_CLIENT_URI
from src.typings import SlotNumber
from src.web3_extentions import LidoContracts, LidoValidatorsProvider, TransactionUtils, KeysAPIClientModule
from tests.mocks import chain_id_mainnet, eth_call_el_rewards_vault, eth_call_beacon_spec
from tests.providers import ResponseToFileProvider, ResponseFromFile, MockProvider, ResponseToFileConsensusClientModule, \
    ResponseFromFileConsensusClientModule


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
    provider = ResponseToFileProvider(EXECUTION_CLIENT_URI)
    yield provider
    provider.save_responses(responses_path)


@pytest.fixture()
def response_to_file_cl_client(web3, responses_path) -> ResponseToFileConsensusClientModule:
    client = ResponseToFileConsensusClientModule(CONSENSUS_CLIENT_URI, web3)
    yield client
    client.save_responses(responses_path.with_suffix('.cl.json'))


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

    # web3.attach_modules({
    #     'lido_contracts': LidoContracts,
    #     'lido_validators': LidoValidatorsProvider,
    #     'transaction': TransactionUtils,
    #     'kac': lambda: KeysAPIClientModule(variables.KEYS_API_URI, web3),
    # })

    yield web3


@pytest.fixture()
def consensus_client(request, responses_path, web3):
    if request.config.getoption("--save-responses"):
        client = request.getfixturevalue("response_to_file_cl_client")
    else:
        client = ResponseFromFileConsensusClientModule(responses_path.with_suffix('.cl.json'), web3)
    web3.attach_modules({"cc": lambda: client})
    return client


@pytest.fixture()
def contracts(web3):
    web3.attach_modules({
        'lido_contracts': LidoContracts,
    })


@pytest.fixture()
def past_slot_and_block(provider):
    return SlotNumber(4595230), '0xc001b15307c51190fb653a885bc9c5003a7b9dacceb75825fa376fc68e1c1a62'
