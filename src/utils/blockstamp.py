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
    pass


def get_blockstamp(
    cc: ConsensusClient,
    slot: SlotNumber,
    last_finalized_slot_number: SlotNumber,
    el: Eth,
) -> BlockStamp:
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
    logger.info({'msg': f'Get Reference Blockstamp for ref slot: {ref_slot}'})
    anchor = _resolve_anchor_block(cc, ref_slot, last_finalized_slot_number)
    logger.info({'msg': f'Resolved to slot: {anchor.message.slot}'})
    return build_reference_blockstamp(anchor, ref_slot, ref_epoch, el)


def get_blockstamp_by_state(cc: ConsensusClient, state: LiteralState, el: Eth) -> BlockStamp:
    """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockRoot"""
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
    """See `ReferenceBlockStamp` for which block a blockstamp is built from."""
    if cc.is_gloas_slot(slot):
        return _get_child_block(cc, slot, last_finalized_slot_number)
    return _get_block_at_or_before(cc, slot, last_finalized_slot_number)


def _get_child_block(
    cc: ConsensusClient, slot: SlotNumber, last_finalized_slot_number: SlotNumber
) -> BlockDetailsResponse:
    child = get_next_non_missed_slot(cc, slot, last_finalized_slot_number)
    if child.message.body.execution_payload is not None:
        raise InconsistentData(
            f'Block at slot [{child.message.slot}] embeds an execution payload, but the beacon '
            f'config puts it after the Gloas fork.'
        )
    return child


def _get_block_at_or_before(
    cc: ConsensusClient, slot: SlotNumber, last_finalized_slot_number: SlotNumber
) -> BlockDetailsResponse:
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
    bid = slot_details.message.body.signed_execution_payload_bid
    if bid is None:
        raise MissingExecutionAnchor(
            f'Block at slot [{slot_details.message.slot}] has neither an execution payload nor a payload bid.'
        )
    return bid.message.parent_block_hash
