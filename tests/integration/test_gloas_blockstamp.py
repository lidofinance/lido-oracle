"""Critical integration checks for the EIP-7732 (Gloas) blockstamp resolution.

These require a Lido devnet with Gloas active and are SKIPPED until one is stable (there is no
public Glamsterdam testnet yet). They encode the highest-risk end-to-end invariants — that a report
blockstamp is built from ref_slot's child and anchored on that child's state.latest_block_hash, and
that the block's bid carries the same value (which is what the liveness path relies on).
"""

import pytest

from src.types import SlotNumber
from src.utils.blockstamp import get_blockstamp_by_state, get_reference_blockstamp


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skip(reason="Requires a Gloas-active devnet; enable once a stable one exists."),
]


def _finalized(web3_integration):
    return get_blockstamp_by_state(web3_integration.cc, 'finalized', web3_integration.eth)


def test_is_gloas__matches_devnet_config(web3_integration):
    finalized = _finalized(web3_integration)
    ref_epoch = finalized.slot_number // web3_integration.cc.get_config_spec().SLOTS_PER_EPOCH
    # On a Gloas-active devnet this must be True for a recent epoch.
    assert web3_integration.cc.is_gloas(ref_epoch) is True


def test_reference_blockstamp__built_from_child_and_anchored_on_state_latest_block_hash(web3_integration):
    finalized = _finalized(web3_integration)
    spec = web3_integration.cc.get_config_spec()
    # Use a ref slot a couple of epochs back so its child is finalized.
    ref_slot = finalized.slot_number - 2 * spec.SLOTS_PER_EPOCH
    ref_epoch = ref_slot // spec.SLOTS_PER_EPOCH

    bs = get_reference_blockstamp(
        web3_integration.cc,
        ref_slot=ref_slot,
        last_finalized_slot_number=finalized.slot_number,
        ref_epoch=ref_epoch,
        el=web3_integration.eth,
    )

    # The report's block is ref_slot's child, and its EL anchor is a real, resolvable EL block.
    assert bs.slot_number > ref_slot
    el_block = web3_integration.eth.get_block(bs.block_hash)
    assert el_block['number'] == bs.block_number

    # The anchor came from the child state; the child block's bid must carry the same value, which
    # is the spec equality the head/finalized path relies on.
    state = web3_integration.cc.get_state_view(bs)
    assert state.slot == bs.slot_number
    assert bs.block_hash.lower() == state.latest_block_hash.lower()

    block = web3_integration.cc.get_block_details(SlotNumber(bs.slot_number))
    bid = block.message.body.signed_execution_payload_bid
    assert bid is not None
    assert bid.message.parent_block_hash.lower() == state.latest_block_hash.lower()
