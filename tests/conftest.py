import os
import socket
from dataclasses import dataclass
from typing import Final, Generator
from unittest.mock import Mock, patch

import pytest
from eth_tester import EthereumTester
from eth_tester.backends.mock import MockBackend
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from web3 import EthereumTesterProvider
from web3.types import Timestamp

from src import variables
from src.providers.execution.base_interface import ContractInterface
from src.providers.ipfs import MultiIPFSProvider
from src.types import BlockNumber, EpochNumber, ReferenceBlockStamp, SlotNumber
from src.web3py.contract_tweak import tweak_w3_contracts
from src.web3py.extensions import (
    CSM,
    ConsensusClientModule,
    KeysAPIClientModule,
    LidoContracts,
    LidoValidatorsProvider,
    TransactionUtils,
)
from src.web3py.types import Web3
from src.web3py.extensions import FallbackProviderModule


@pytest.fixture(autouse=True)
def disable_network_for_unit(request):
    if request.node.get_closest_marker('unit'):

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


DUMMY_ADDRESS = "0x0000000000000000000000000000000000000000"


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
            'ipfs': lambda: Mock(spec=MultiIPFSProvider),
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
        }
    )

    yield w3


@pytest.fixture()
def contracts(web3, monkeypatch):
    # TODO: Will be applied for mainnet tests only in next PR
    monkeypatch.setattr(variables, 'LIDO_LOCATOR_ADDRESS', '0xC1d0b3DE6792Bf6b4b37EccdcC24e45978Cfd2Eb')
    monkeypatch.setattr(variables, 'CSM_MODULE_ADDRESS', '0xdA7dE2ECdDfccC6c3AF10108Db212ACBBf9EA83F')


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


# TODO: Will be applied for testnet tests only in next PR
# Primary usage of TESTNET_CONSENSUS_CLIENT_URI is for tests which can't run with mainnet node.
TESTNET_CONSENSUS_CLIENT_URI: Final = os.getenv('TESTNET_CONSENSUS_CLIENT_URI', '').split(',')


@dataclass
class Account:
    address: ChecksumAddress
    _private_key: HexBytes
