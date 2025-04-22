"""Execution node"""
import pytest

from src.providers.execution.contracts.deposit_contract import DepositContract
from src.utils.events import get_events_in_range

get_deposit_count_abi = {
    "inputs": [],
    "name": "get_deposit_count",
    "outputs": [
        {'internalType': "bytes", 'name': "", 'type': "bytes"}
    ],
    "stateMutability": "view",
    "type": "function"
}

deposit_event_abi = {'anonymous': False, 'inputs': [
    {'indexed': False, 'internalType': "bytes", 'name': "pubkey", 'type': "bytes"},
    {'indexed': False, 'internalType': "bytes", 'name': "withdrawal_credentials", 'type': "bytes"},
    {'indexed': False, 'internalType': "bytes", 'name': "amount", 'type': "bytes"},
    {'indexed': False, 'internalType': "bytes", 'name': "signature", 'type': "bytes"},
    {'indexed': False, 'internalType': "bytes", 'name': "index", 'type': "bytes"}
], 'name': "DepositEvent", 'type': "event"}


@pytest.fixture
def deposit_contract(web3):
    cc_config = web3.cc.get_config_spec()
    return web3.eth.contract(
        address=web3.to_checksum_address(cc_config.DEPOSIT_CONTRACT_ADDRESS),
        ContractFactoryClass=DepositContract,
        decode_tuples=True,
    )


def check_eth_call_availability(blockstamp, deposit_contract):
    """Check that execution-client able to make eth_call on the provided blockstamp"""
    deposit_contract.get_deposit_count(block_identifier=blockstamp.block_hash)


def check_balance_availability(web3, blockstamp, deposit_contract):
    """Check that execution-client able to get balance on the provided blockstamp"""
    web3.eth.get_balance(deposit_contract.address, block_identifier=blockstamp.block_hash)


def check_events_range_availability(deposit_contract, blockstamp, finalized_blockstamp):
    """Check that execution-client able to get event logs in a range"""
    events = list(
        get_events_in_range(
            deposit_contract.events.DepositEvent,
            l_block=blockstamp.block_number,
            r_block=finalized_blockstamp.block_number,
        )
    )
    deposits_count_before = deposit_contract.get_deposit_count(blockstamp.block_number - 1)
    deposits_count_now = deposit_contract.get_deposit_count(finalized_blockstamp.block_hash)
    assert deposits_count_now >= deposits_count_before, "Deposits count decreased"
    assert len(events) == (deposits_count_now - deposits_count_before), "Events count doesn't match deposits count"
