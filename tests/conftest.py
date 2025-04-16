import os
from dataclasses import dataclass
from typing import Final
from unittest.mock import Mock

import pytest
from eth_tester import EthereumTester
from eth_tester.backends.mock import MockBackend
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from web3 import EthereumTesterProvider
from web3.types import Timestamp

import src.variables
from src.types import BlockNumber, EpochNumber, ReferenceBlockStamp, SlotNumber
from src.web3py.contract_tweak import tweak_w3_contracts
from src.web3py.extensions import (
    ConsensusClientModule,
    KeysAPIClientModule,
    LazyCSM,
    LidoContracts,
    LidoValidatorsProvider,
    TransactionUtils,
)
from src.web3py.types import Web3
from unittest.mock import patch

@pytest.fixture()
def web3():
    mock_backend = MockBackend()
    tester = EthereumTester(backend=mock_backend)
    web3 = Web3(provider=EthereumTesterProvider(tester))
    tweak_w3_contracts(web3)
    web3.attach_modules(
        {
            'lido_contracts': lambda: Mock(),
            'lido_validators': LidoValidatorsProvider,
            'transaction': TransactionUtils,
            'csm': LazyCSM,
            'cc': lambda: ConsensusClientModule('http://localhost:8080', web3),  # TODO: to mock
            'kac': lambda: KeysAPIClientModule('http://localhost:8080', web3),  # TODO: to mock
            'ipfs': lambda: Mock(),
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


# Primary usage of TESTNET_CONSENSUS_CLIENT_URI is for tests which can't run with mainnet node.
TESTNET_CONSENSUS_CLIENT_URI: Final = os.getenv('TESTNET_CONSENSUS_CLIENT_URI', '').split(',')


@dataclass
class Account:
    address: ChecksumAddress
    _private_key: HexBytes
