"""Consensus node"""

from src.web3py.types import Web3


def check_validators_provided(web3: Web3, blockstamp):
    """Check that consensus-client able to provide validators"""
    assert web3.cc.get_validators_no_cache(blockstamp), "consensus-client provide no validators"


def check_block_details_provided(web3: Web3, blockstamp):
    """Check that consensus-client able to provide block details"""
    assert web3.cc.get_block_details(blockstamp.slot_number), "consensus-client provide no block details"


def check_block_root_provided(web3: Web3, blockstamp):
    """Check that consensus-client able to provide block root"""
    assert web3.cc.get_block_root(blockstamp.slot_number), "consensus-client provide no block root"


def check_block_header_provided(web3: Web3, blockstamp):
    """Check that consensus-client able to provide block header"""
    assert web3.cc.get_block_header(blockstamp.slot_number), "consensus-client provide no block header"


def check_block_roots_from_state_provided(web3: Web3, blockstamp):
    """Check that consensus-client able to provide block roots from state"""
    assert web3.cc.get_state_block_roots(blockstamp.slot_number), "consensus-client provide no block roots from state"


def check_attestation_committees(web3: Web3, blockstamp):
    """Check that consensus-client able to provide attestation committees"""
    cc_config = web3.cc.get_config_spec()
    slots_per_epoch = cc_config.SLOTS_PER_EPOCH
    epoch = blockstamp.slot_number // slots_per_epoch - cc_config.SLOTS_PER_HISTORICAL_ROOT // slots_per_epoch
    assert web3.cc.get_attestation_committees(blockstamp, epoch), "consensus-client provide no attestation committees"


def check_sync_committee(web3: Web3, blockstamp):
    """Check that consensus-client able to provide sync committee"""
    cc_config = web3.cc.get_config_spec()
    slots_per_epoch = cc_config.SLOTS_PER_EPOCH
    epoch = blockstamp.slot_number // slots_per_epoch
    assert web3.cc.get_sync_committee(blockstamp, epoch), "consensus-client provide no sync committee"


def check_block_attestations_and_sync(web3: Web3, blockstamp):
    """Check that consensus-client able to provide block attestations"""
    assert web3.cc.get_block_attestations_and_sync(blockstamp.slot_number), "consensus-client provide no block attestations and sync"
