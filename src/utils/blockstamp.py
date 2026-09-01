import logging
from dataclasses import asdict

from eth_typing import BlockNumber
from eth_utils.hexadecimal import add_0x_prefix
from web3.eth import Eth
from web3.types import Timestamp

from src.metrics.prometheus.basic import ORACLE_BLOCK_NUMBER, ORACLE_SLOT_NUMBER
from src.providers.consensus.client import ConsensusClient, LiteralState
from src.providers.consensus.types import BlockDetailsResponse, ExecutionPayload
from src.providers.execution.exceptions import InconsistentData
from src.types import BlockHash, BlockStamp, EpochNumber, ReferenceBlockStamp, SlotNumber
from src.utils.slot import get_next_non_missed_slot, get_prev_non_missed_slot


logger = logging.getLogger(__name__)


class MissingExecutionAnchor(Exception):
    """Raised when a post-EIP-7732 block's execution-layer anchor cannot be read."""


def get_blockstamp(
    cc: ConsensusClient,
    slot: SlotNumber,
    last_finalized_slot_number: SlotNumber,
    el: Eth,
) -> BlockStamp:
    """Build a BlockStamp for `slot` from its anchor block."""
    logger.info({'msg': f'Get Blockstamp for slot: {slot}'})
    anchor = _resolve_anchor_block(cc, slot, last_finalized_slot_number)
    logger.info({'msg': f'Resolved to slot: {anchor.message.slot}'})
    return build_blockstamp(anchor, el)


def get_reference_blockstamp(
    cc: ConsensusClient,
    ref_slot: SlotNumber,
    last_finalized_slot_number: SlotNumber,
    ref_epoch: EpochNumber,
    el: Eth,
) -> ReferenceBlockStamp:
    """Build a ReferenceBlockStamp for `ref_slot` from its anchor block."""
    logger.info({'msg': f'Get Reference Blockstamp for ref slot: {ref_slot}'})
    anchor = _resolve_anchor_block(cc, ref_slot, last_finalized_slot_number)
    logger.info({'msg': f'Resolved to slot: {anchor.message.slot}'})
    return build_reference_blockstamp(anchor, ref_slot, ref_epoch, el)


def get_blockstamp_by_state(cc: ConsensusClient, state: LiteralState, el: Eth) -> BlockStamp:
    """Fetch the block for the given chain state (head/finalized/...) and build a BlockStamp.

    The chain tip has no child yet, so the stamp is built from the block itself.
    """
    block_root = cc.get_block_root(state).root
    block_details = cc.get_block_details(block_root)
    bs = build_blockstamp(block_details, el)
    logger.info({'msg': f'Fetch {state} blockstamp.', 'value': asdict(bs)})
    ORACLE_SLOT_NUMBER.labels(state).set(bs.slot_number)
    ORACLE_BLOCK_NUMBER.labels(state).set(bs.block_number)
    return bs


def build_blockstamp(slot_details: BlockDetailsResponse, el: Eth) -> BlockStamp:
    return BlockStamp(**_get_base_fields(slot_details, el))


def build_reference_blockstamp(
    slot_details: BlockDetailsResponse,
    ref_slot: SlotNumber,
    ref_epoch: EpochNumber,
    el: Eth,
) -> ReferenceBlockStamp:
    return ReferenceBlockStamp(
        **_get_base_fields(slot_details, el),
        ref_slot=ref_slot,
        ref_epoch=ref_epoch,
    )


def _resolve_anchor_block(
    cc: ConsensusClient, slot: SlotNumber, last_finalized_slot_number: SlotNumber
) -> BlockDetailsResponse:
    """The beacon block a blockstamp for `slot` is built from: `slot` itself pre-EIP-7732, its child
    post-fork.

    Which side of the fork `slot` falls on comes from the beacon config, so a missed slot at the
    fork boundary cannot send the resolution down the wrong branch — reading it off the block shape
    could, because the block before a missed post-fork slot may still be a pre-fork one. The shape
    is kept as a cross-check: pre-fork blocks embed their payload and post-fork ones do not, so a
    disagreement means the config does not describe the chain we are reading.
    """
    if cc.is_gloas_slot(slot):
        child = get_next_non_missed_slot(cc, slot, last_finalized_slot_number)
        if child.message.body.execution_payload is not None:
            raise InconsistentData(
                f'Block at slot [{child.message.slot}] embeds an execution payload, but the beacon '
                f'config puts it after the Gloas fork.'
            )
        return child

    block = get_prev_non_missed_slot(cc, slot, last_finalized_slot_number)
    if block.message.body.execution_payload is None:
        raise InconsistentData(
            f'Block at slot [{block.message.slot}] has no execution payload, but the beacon config '
            f'puts it before the Gloas fork.'
        )
    return block


def _get_base_fields(slot_details: BlockDetailsResponse, el: Eth) -> dict:
    return {
        "slot_number": slot_details.message.slot,
        "state_root": slot_details.message.state_root,
        **_get_el_fields(slot_details, el),
    }


def _get_el_fields(slot_details: BlockDetailsResponse, el: Eth) -> dict:
    payload = slot_details.message.body.execution_payload
    if payload is not None:
        # Pre-EIP-7732: the block embeds the execution payload it was built with.
        return _get_el_fields_from_payload(payload)

    return _get_el_fields_from_hash(el, _get_anchor_hash(slot_details))


def _get_el_fields_from_payload(execution_payload: ExecutionPayload) -> dict:
    return {
        "block_number": execution_payload.block_number,
        "block_hash": add_0x_prefix(execution_payload.block_hash),
        "block_timestamp": execution_payload.timestamp,
    }


def _get_el_fields_from_hash(el: Eth, el_block_hash: BlockHash) -> dict:
    block = el.get_block(el_block_hash)
    return {
        "block_number": BlockNumber(block["number"]),  # type: ignore[typeddict-item]
        "block_hash": add_0x_prefix(el_block_hash),
        "block_timestamp": Timestamp(block["timestamp"]),  # type: ignore[typeddict-item]
    }


def _get_anchor_hash(slot_details: BlockDetailsResponse) -> BlockHash:
    """The post-EIP-7732 execution-layer anchor: the last execution block applied to this block's
    state, read out of the block's own payload bid.

    `process_execution_payload_bid` asserts `bid.parent_block_hash == state.latest_block_hash`, and
    `process_parent_execution_payload` preserves that in both branches, so the bid carries the value
    the state would report. Reading it from the block body keeps every blockstamp off
    `debug/beacon/states`, which returns the whole state and is not affordable per daemon cycle.
    """
    bid = slot_details.message.body.signed_execution_payload_bid
    if bid is None:
        raise MissingExecutionAnchor(
            f'Block at slot [{slot_details.message.slot}] has neither an execution payload nor a payload bid.'
        )
    return bid.message.parent_block_hash
