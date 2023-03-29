"""Consensus node"""
from src.web3py.typings import Web3


def check_validators_provided(web3: Web3, blockstamp):
    """Check that consensus-client able to provide validators"""
    result = web3.cc.get_validators_no_cache(blockstamp)
    assert len(result) > 0, "consensus-client provide no validators"


def check_block_details_provided(web3: Web3, blockstamp):
    """Check that consensus-client able to provide block details"""
    web3.cc.get_block_details(blockstamp.slot_number)


def check_block_root_provided(web3: Web3, blockstamp):
    """Check that consensus-client able to provide block root"""
    web3.cc.get_block_root(blockstamp.slot_number)


def check_block_header_provided(web3: Web3, blockstamp):
    """Check that consensus-client able to provide block header"""
    web3.cc.get_block_header(blockstamp.slot_number)
