"""Execution node"""
from eth_typing import BlockNumber
import pytest

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
        abi=[get_deposit_count_abi, deposit_event_abi],
    )


def check_eth_call_availability(blockstamp, deposit_contract):
    """Check that execution-client able to make eth_call on the provided blockstamp"""
    deposit_contract.functions.get_deposit_count().call(block_identifier=blockstamp.block_hash)


def check_balance_availability(web3, blockstamp, deposit_contract):
    """Check that execution-client able to get balance on the provided blockstamp"""
    web3.eth.get_balance(deposit_contract.address, block_identifier=blockstamp.block_hash)


def check_events_range_availability(web3, blockstamp, deposit_contract):
    """Check that execution-client able to get event logs on the blockstamp state"""
    latest_block = web3.eth.get_block('latest')
    list(get_events_in_range(deposit_contract.events.DepositEvent, blockstamp.block_number, latest_block.number))


@pytest.mark.parametrize('range_', [8 * 225 * 32, 32 * 225 * 32], ids=['week', 'month'])
def check_events_week_range_availability(web3, deposit_contract, range_):
    """Check that execution-client able to get event logs in a range"""
    def _get_deposit_count(block):
        return int.from_bytes(
            deposit_contract.functions.get_deposit_count().call(block_identifier=block), 'little'
        )

    latest_block = web3.eth.get_block('latest')
    from_block = max(0, latest_block.number - range_)
    to_block = latest_block.number
    events = list(
        get_events_in_range(
            deposit_contract.events.DepositEvent,
            l_block=BlockNumber(from_block),
            r_block=to_block,
        )
    )
    deposits_count_before = _get_deposit_count(from_block)
    deposits_count_now = _get_deposit_count(to_block)
    assert deposits_count_now >= deposits_count_before, "Deposits count decreased"
    if deposits_in_range := deposits_count_now - deposits_count_before:
        assert len(events) == deposits_in_range, "Events count doesn't match deposits count"
