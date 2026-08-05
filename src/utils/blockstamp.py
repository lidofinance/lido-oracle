import logging
from dataclasses import asdict

from eth_utils.hexadecimal import add_0x_prefix

from src.metrics.prometheus.basic import ORACLE_BLOCK_NUMBER, ORACLE_SLOT_NUMBER
from src.providers.consensus.client import ConsensusClient, LiteralState
from src.providers.consensus.types import BlockDetailsResponse
from src.types import BlockStamp, EpochNumber, ReferenceBlockStamp, SlotNumber


logger = logging.getLogger(__name__)


def build_reference_blockstamp(
    slot_details: BlockDetailsResponse,
    ref_slot: SlotNumber,
    ref_epoch: EpochNumber,
) -> ReferenceBlockStamp:
    return ReferenceBlockStamp(
        **_build_blockstamp_data(slot_details),
        ref_slot=ref_slot,
        ref_epoch=ref_epoch,
    )


def build_blockstamp(slot_details: BlockDetailsResponse):
    return BlockStamp(**_build_blockstamp_data(slot_details))


def get_blockstamp_by_state(cc: ConsensusClient, state: LiteralState) -> BlockStamp:
    """Fetch the block for the given chain state and build a BlockStamp from it."""
    block_root = cc.get_block_root(state).root
    block_details = cc.get_block_details(block_root)
    bs = build_blockstamp(block_details)
    logger.info({'msg': f'Fetch {state} blockstamp.', 'value': asdict(bs)})
    ORACLE_SLOT_NUMBER.labels(state).set(bs.slot_number)
    ORACLE_BLOCK_NUMBER.labels(state).set(bs.block_number)
    return bs


def _build_blockstamp_data(
    slot_details: BlockDetailsResponse,
) -> dict:
    execution_payload = slot_details.message.body.execution_payload

    return {
        "slot_number": slot_details.message.slot,
        "state_root": slot_details.message.state_root,
        "block_number": execution_payload.block_number,
        "block_hash": add_0x_prefix(execution_payload.block_hash),
        "block_timestamp": execution_payload.timestamp,
    }
