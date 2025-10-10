import os
import socket
from typing import Final, Generator
from unittest.mock import Mock, patch

import pytest
from eth_tester import EthereumTester
from eth_tester.backends.mock import MockBackend
from web3 import EthereumTesterProvider

from src import variables
from src.main import ipfs_providers
from src.providers.execution.base_interface import ContractInterface
from src.web3py.contract_tweak import tweak_w3_contracts
from src.web3py.extensions import (
    CSM,
    IPFS,
    ConsensusClientModule,
    FallbackProviderModule,
    KeysAPIClientModule,
    LidoContracts,
    LidoValidatorsProvider,
    TransactionUtils,
)
from src.web3py.types import Web3

UNIT_MARKER = 'unit'
INTEGRATION_MARKER = 'integration'
MAINNET_MARKER = 'mainnet'
TESTNET_MARKER = 'testnet'

DUMMY_ADDRESS = "0x0000000000000000000000000000000000000000"

# The primary usage is for tests that can't run with the mainnet node.
TESTNET_CONSENSUS_CLIENT_URI: Final = os.getenv('TESTNET_CONSENSUS_CLIENT_URI', '').split(',')
TESTNET_EXECUTION_CLIENT_URI: Final = os.getenv('TESTNET_EXECUTION_CLIENT_URI', '').split(',')
TESTNET_KAPI_URI: Final = os.getenv('TESTNET_KAPI_URI', '').split(',')


@pytest.fixture(autouse=True)
def check_test_marks_compatibility(request):
    all_test_markers = {x.name for x in request.node.iter_markers()}

    if not all_test_markers:
        pytest.fail('Test must be marked.')

    elif UNIT_MARKER in all_test_markers and {MAINNET_MARKER, TESTNET_MARKER, INTEGRATION_MARKER} & all_test_markers:
        pytest.fail('Test can not be both unit and integration at the same time.')

    elif {MAINNET_MARKER, TESTNET_MARKER} & all_test_markers and INTEGRATION_MARKER not in all_test_markers:
        pytest.fail('Test can not be run on mainnet or testnet without integration marker.')


@pytest.fixture(autouse=True)
def configure_unit_tests(request):
    if request.node.get_closest_marker(UNIT_MARKER):

        def blocked_connect(*args, **kwargs):
            msg = (
                'Network access deprecated in unit test! '
                'Use mocks instead of real network calls. '
                f'Attempted connection: args={args}, kwargs={kwargs}'
            )
            pytest.fail(msg)

        with patch.object(socket.socket, 'connect', blocked_connect):
            yield
    else:
        yield


@pytest.fixture(autouse=True)
def configure_mainnet_tests(request, monkeypatch):
    if request.node.get_closest_marker(MAINNET_MARKER):
        if not all(
            x[0] for x in [variables.CONSENSUS_CLIENT_URI, variables.EXECUTION_CLIENT_URI, variables.KEYS_API_URI]
        ):
            pytest.fail(
                'CONSENSUS_CLIENT_URI, EXECUTION_CLIENT_URI and KEYS_API_URI '
                'must be set in order to run tests on mainnet.'
            )

        monkeypatch.setattr(variables, 'LIDO_LOCATOR_ADDRESS', '0xC1d0b3DE6792Bf6b4b37EccdcC24e45978Cfd2Eb')
        monkeypatch.setattr(variables, 'CSM_MODULE_ADDRESS', '0xdA7dE2ECdDfccC6c3AF10108Db212ACBBf9EA83F')

    yield


@pytest.fixture(autouse=True)
def configure_testnet_tests(request, monkeypatch):
    if request.node.get_closest_marker(TESTNET_MARKER):
        if not all(x[0] for x in [TESTNET_CONSENSUS_CLIENT_URI, TESTNET_EXECUTION_CLIENT_URI, TESTNET_KAPI_URI]):
            pytest.fail(
                'TESTNET_CONSENSUS_CLIENT_URI, TESTNET_EXECUTION_CLIENT_URI and TESTNET_KAPI_URI '
                'must be set in order to run tests on testnet.'
            )

        # Works only if module fully imported, e.g.
        # "from src import variables" not "from src.variables import <ENV>"
        monkeypatch.setattr(variables, 'CONSENSUS_CLIENT_URI', TESTNET_CONSENSUS_CLIENT_URI)
        monkeypatch.setattr(variables, 'EXECUTION_CLIENT_URI', TESTNET_EXECUTION_CLIENT_URI)
        monkeypatch.setattr(variables, 'KEYS_API_URI', TESTNET_KAPI_URI)

        monkeypatch.setattr(variables, 'LIDO_LOCATOR_ADDRESS', '0xe2EF9536DAAAEBFf5b1c130957AB3E80056b06D8')
        monkeypatch.setattr(variables, 'CSM_MODULE_ADDRESS', '0x79cef36d84743222f37765204bec41e92a93e59d')

    yield


@pytest.fixture()
def web3(monkeypatch) -> Generator[Web3, None, None]:
    mock_backend = MockBackend()
    tester = EthereumTester(backend=mock_backend)
    w3 = Web3(provider=EthereumTesterProvider(tester))
    tweak_w3_contracts(w3)

    monkeypatch.setattr(variables, 'LIDO_LOCATOR_ADDRESS', DUMMY_ADDRESS)
    monkeypatch.setattr(variables, 'CSM_MODULE_ADDRESS', DUMMY_ADDRESS)

    def create_contract_mock(*args, **kwargs):
        """
        Idea here is to create a contract mock that by default returns mock objects
        for all contract method calls. If a test requires a specific contract method to return
        a particular value instead of mock, you need to configure the return value for that method
        directly in the test.

        """

        contract_factory_class = kwargs.get('ContractFactoryClass', ContractInterface)
        decode_tuples = kwargs.get('decode_tuples', True)

        mock_contract = Mock(spec=contract_factory_class)
        mock_contract.address = DUMMY_ADDRESS
        mock_contract.decode_tuples = decode_tuples
        mock_contract.abi = contract_factory_class.load_abi(contract_factory_class.abi_path)

        return mock_contract

    w3.eth.contract = create_contract_mock

    w3.attach_modules(
        {
            # Mocked on the contract level, see create_contract_mock
            'lido_contracts': LidoContracts,
            'transaction': TransactionUtils,
            'csm': CSM,
            'lido_validators': LidoValidatorsProvider,
            # Modules relying on network level highly - mocked fully
            'cc': lambda: Mock(spec=ConsensusClientModule),
            'kac': lambda: Mock(spec=KeysAPIClientModule),
            'ipfs': lambda: Mock(spec=IPFS),
        }
    )

    yield w3


@pytest.fixture()
def web3_integration() -> Generator[Web3, None, None]:
    w3 = Web3(
        FallbackProviderModule(
            variables.EXECUTION_CLIENT_URI,
            request_kwargs={'timeout': variables.HTTP_REQUEST_TIMEOUT_EXECUTION},
            cache_allowed_requests=True,
        )
    )
    tweak_w3_contracts(w3)

    w3.attach_modules(
        {
            'lido_contracts': LidoContracts,
            'lido_validators': LidoValidatorsProvider,
            'transaction': TransactionUtils,
            'cc': lambda: ConsensusClientModule(variables.CONSENSUS_CLIENT_URI, w3),
            'kac': lambda: KeysAPIClientModule(variables.KEYS_API_URI, w3),
            'ipfs': lambda: IPFS(w3, ipfs_providers(), retries=variables.HTTP_REQUEST_RETRY_COUNT_IPFS),
        }
    )

    yield w3
