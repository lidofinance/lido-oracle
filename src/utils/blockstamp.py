import logging
from collections.abc import Callable
from dataclasses import asdict
from functools import partial

from eth_typing import BlockNumber, HexStr
from eth_utils.hexadecimal import add_0x_prefix
from web3.eth import Eth
from web3.types import Timestamp

from src.metrics.prometheus.basic import ORACLE_BLOCK_NUMBER, ORACLE_SLOT_NUMBER
from src.providers.consensus.client import ConsensusClient, LiteralState
from src.providers.consensus.types import BlockDetailsResponse, ExecutionPayload
from src.types import BlockHash, BlockStamp, EpochNumber, ReferenceBlockStamp, SlotNumber
from src.utils.slot import get_next_non_missed_slot, get_prev_non_missed_slot


logger = logging.getLogger(__name__)

AnchorHashResolver = Callable[[BlockDetailsResponse], BlockHash]


class MissingExecutionAnchor(Exception):
    """Raised when a post-EIP-7732 block's execution-layer anchor cannot be read."""


# CL-only consumers (the performance collector) read only slot_number and state_root. They have no
# execution client, and post-EIP-7732 an anchor cannot be resolved into a block without one.
_PLACEHOLDER_EL_FIELDS: dict = {
    "block_number": BlockNumber(0),
    "block_hash": BlockHash(add_0x_prefix(HexStr('00' * 32))),
    "block_timestamp": Timestamp(0),
}


def get_blockstamp(
    cc: ConsensusClient,
    slot: SlotNumber,
    last_finalized_slot_number: SlotNumber,
    el: Eth | None = None,
) -> BlockStamp:
    """Build a BlockStamp for `slot` from its anchor block."""
    logger.info({'msg': f'Get Blockstamp for slot: {slot}'})
    anchor = _resolve_anchor_block(cc, slot, last_finalized_slot_number)
    logger.info({'msg': f'Resolved to slot: {anchor.message.slot}'})
    return build_blockstamp(cc, anchor, el)


def get_reference_blockstamp(
    cc: ConsensusClient,
    ref_slot: SlotNumber,
    last_finalized_slot_number: SlotNumber,
    ref_epoch: EpochNumber,
    el: Eth | None = None,
) -> ReferenceBlockStamp:
    """Build a ReferenceBlockStamp for `ref_slot` from its anchor block."""
    logger.info({'msg': f'Get Reference Blockstamp for ref slot: {ref_slot}'})
    anchor = _resolve_anchor_block(cc, ref_slot, last_finalized_slot_number)
    logger.info({'msg': f'Resolved to slot: {anchor.message.slot}'})
    return build_reference_blockstamp(cc, anchor, ref_slot, ref_epoch, el)


def get_blockstamp_by_state(cc: ConsensusClient, state: LiteralState, el: Eth | None = None) -> BlockStamp:
    """Fetch the block for the given chain state (head/finalized/...) and build a BlockStamp.

    The chain tip has no child yet, so the stamp is built from the block itself and takes its
    execution anchor from the block's own bid rather than from beacon state.
    """
    block_root = cc.get_block_root(state).root
    block_details = cc.get_block_details(block_root)
    bs = BlockStamp(**_get_base_fields(block_details, el, _get_anchor_hash_from_bid))
    logger.info({'msg': f'Fetch {state} blockstamp.', 'value': asdict(bs)})
    ORACLE_SLOT_NUMBER.labels(state).set(bs.slot_number)
    ORACLE_BLOCK_NUMBER.labels(state).set(bs.block_number)
    return bs


def build_blockstamp(cc: ConsensusClient, slot_details: BlockDetailsResponse, el: Eth | None = None) -> BlockStamp:
    return BlockStamp(**_get_base_fields(slot_details, el, partial(_get_anchor_hash_from_state, cc)))


def build_reference_blockstamp(
    cc: ConsensusClient,
    slot_details: BlockDetailsResponse,
    ref_slot: SlotNumber,
    ref_epoch: EpochNumber,
    el: Eth | None = None,
) -> ReferenceBlockStamp:
    return ReferenceBlockStamp(
        **_get_base_fields(slot_details, el, partial(_get_anchor_hash_from_state, cc)),
        ref_slot=ref_slot,
        ref_epoch=ref_epoch,
    )


def _resolve_anchor_block(
    cc: ConsensusClient, slot: SlotNumber, last_finalized_slot_number: SlotNumber
) -> BlockDetailsResponse:
    """The beacon block a blockstamp for `slot` is built from: `slot` itself pre-EIP-7732, its child
    post-fork.

    The fork is read off the block shape — an embedded execution payload means pre-fork — because a
    beacon-config fork epoch would silently pick the wrong branch if its key were missing or renamed.
    """
    block = get_prev_non_missed_slot(cc, slot, last_finalized_slot_number)
    if block.message.body.execution_payload is not None:
        return block
    return get_next_non_missed_slot(cc, slot, last_finalized_slot_number)


def _get_base_fields(slot_details: BlockDetailsResponse, el: Eth | None, get_anchor_hash: AnchorHashResolver) -> dict:
    return {
        "slot_number": slot_details.message.slot,
        "state_root": slot_details.message.state_root,
        **_get_el_fields(slot_details, el, get_anchor_hash),
    }


def _get_el_fields(slot_details: BlockDetailsResponse, el: Eth | None, get_anchor_hash: AnchorHashResolver) -> dict:
    payload = slot_details.message.body.execution_payload
    if payload is not None:
        # Pre-EIP-7732: the block embeds the execution payload it was built with.
        return _get_el_fields_from_payload(payload)

    if el is None:
        return dict(_PLACEHOLDER_EL_FIELDS)

    return _get_el_fields_from_hash(el, get_anchor_hash(slot_details))


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


def _get_anchor_hash_from_state(cc: ConsensusClient, slot_details: BlockDetailsResponse) -> BlockHash:
    """The authoritative anchor: the latest execution block applied to the block's own state.

    Reports pay nothing extra for it. They read that same state for validators and pending_deposits,
    and `get_state_view` keys its cache on `(state_root, slot)`, so both reads hit one entry.
    """
    slot = slot_details.message.slot
    anchor = cc.get_state_view((slot_details.message.state_root, slot)).latest_block_hash
    if not anchor:
        raise MissingExecutionAnchor(f'State at slot [{slot}] has no latest_block_hash.')
    return anchor


def _get_anchor_hash_from_bid(slot_details: BlockDetailsResponse) -> BlockHash:
    """The same anchor read out of the block body, for stamps that must not download a state.

    Head and finalized stamps are rebuilt every daemon cycle and need only a block hash for
    `eth_call`s, so a multi-gigabyte state download per cycle is not an option.
    `process_execution_payload_bid` asserts `bid.parent_block_hash == state.latest_block_hash`.
    """
    bid = slot_details.message.body.signed_execution_payload_bid
    if bid is None:
        raise MissingExecutionAnchor(
            f'Block at slot [{slot_details.message.slot}] has neither an execution payload nor a payload bid.'
        )
    return bid.message.parent_block_hash
