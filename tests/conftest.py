import os
import socket
from dataclasses import dataclass
from typing import Final
from unittest.mock import Mock, patch

import pytest
from eth_tester import EthereumTester
from eth_tester.backends.mock import MockBackend
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from web3 import EthereumTesterProvider
from web3.types import Timestamp

import src.variables
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
def web3():
    mock_backend = MockBackend()
    tester = EthereumTester(backend=mock_backend)
    web3 = Web3(provider=EthereumTesterProvider(tester))
    tweak_w3_contracts(web3)

    src.variables.LIDO_LOCATOR_ADDRESS = DUMMY_ADDRESS
    src.variables.CSM_MODULE_ADDRESS = DUMMY_ADDRESS

    def create_contract_mock(*args, **kwargs):
        """
        Idea here is to create a contract mock that by default returns mock objects
        for all contract method calls. If a test requires a specific contract method to return
        a particular value instead of mock, you need to configure the return value for that method
        directly in the test.

        """

        contract_factory_class = kwargs.get('ContractFactoryClass', ContractInterface)
        decode_tuples = kwargs.get('decode_tuples', True)

        # Idea here is to mock all contracts functions and return mocks as a result of calling them.
        # However, there are many places in code where something but not mock is expected.
        # In this case, you should add a return value to a specific function in a contract mock inside the test.
        mock_contract = Mock(spec=contract_factory_class)
        mock_contract.address = DUMMY_ADDRESS
        mock_contract.decode_tuples = decode_tuples
        mock_contract.abi = contract_factory_class.load_abi(contract_factory_class.abi_path)

        return mock_contract

    web3.eth.contract = create_contract_mock

    web3.attach_modules(
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
    yield web3


@pytest.fixture()
def consensus_client(request, web3):
    # TODO: Deprecated, will be removed in next PR
    pass


@pytest.fixture()
def keys_api_client(request, web3):
    # TODO: Deprecated, will be removed in next PR
    pass


@pytest.fixture()
def csm(web3):
    # TODO: Deprecated, will be removed in next PR
    pass


@pytest.fixture()
def contracts(web3):
    # TODO: Will be applied for mainnet tests only in next PR
    src.variables.LIDO_LOCATOR_ADDRESS = "0x548C1ED5C83Bdf19e567F4cd7Dd9AC4097088589"
    src.variables.CSM_MODULE_ADDRESS = "0xdA7dE2ECdDfccC6c3AF10108Db212ACBBf9EA83F"


@pytest.fixture()
def tx_utils(web3):
    # TODO: Deprecated, will be removed in next PR
    pass


@pytest.fixture()
def lido_validators(web3):
    # TODO: Deprecated, will be removed in next PR
    pass


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
