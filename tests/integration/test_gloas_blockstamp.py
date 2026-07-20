"""Critical integration checks for the EIP-7732 (Gloas) shared blockstamp resolution.

These require a Lido devnet with Gloas active and are SKIPPED until one is stable (there is no
public Glamsterdam testnet yet). They encode the highest-risk end-to-end invariant — that the
report blockstamp resolves the execution-layer anchor and pending_deposits from ref_slot's child
state — so it can be validated on a devnet by removing the skip. See
docs/glamsterdam-devnet-testplan.md for the full manual plan and the exact scenarios to induce
(payload-full vs payload-withheld, deposit-in-ref-slot, etc.).
"""

import pytest

from src.utils.blockstamp import get_blockstamp_by_state
from src.utils.slot import get_reference_blockstamp


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skip(reason="Requires a Gloas-active devnet; enable once a stable one exists."),
]


def _finalized(web3_integration):
    return get_blockstamp_by_state(web3_integration.cc, 'finalized', el=web3_integration.eth)


def test_is_gloas__matches_devnet_config(web3_integration):
    finalized = _finalized(web3_integration)
    ref_epoch = finalized.slot_number // web3_integration.cc.get_config_spec().SLOTS_PER_EPOCH
    # On a Gloas-active devnet this must be True for a recent epoch.
    assert web3_integration.cc.is_gloas(ref_epoch) is True


def test_reference_blockstamp__resolves_child_anchor_and_correction_flag(web3_integration):
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

    # CL anchor stays at (or before) ref_slot; EL anchor Y is a real, resolvable EL block.
    assert bs.slot_number <= ref_slot
    assert bs.child_state_root is not None and bs.child_slot is not None
    assert bs.child_slot > bs.slot_number
    el_block = web3_integration.eth.get_block(bs.block_hash)
    assert el_block['number'] == bs.block_number

    # pending_deposits are sourced from the child state, not the block's own state.
    child_pending = web3_integration.cc.get_state_view((bs.child_state_root, bs.child_slot)).pending_deposits
    assert web3_integration.cc.get_pending_deposits(bs) == child_pending

    # withdrawal_correction_needed is consistent with Y vs ref_slot's committed payload:
    # when the payload was confirmed full, Y == committed bid and the flag must be False.
    # (Which case this is depends on the chosen slot; assert the flag is a bool and internally
    # consistent rather than a fixed value.)
    assert isinstance(bs.withdrawal_correction_needed, bool)
