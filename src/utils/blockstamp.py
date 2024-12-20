from web3.types import Timestamp

from src.providers.consensus.types import BlockDetailsResponse
from src.types import SlotNumber, EpochNumber, ReferenceBlockStamp, BlockStamp, BlockNumber


def build_reference_blockstamp(
    slot_details: BlockDetailsResponse,
    ref_slot: SlotNumber,
    ref_epoch: EpochNumber,
) -> ReferenceBlockStamp:
    return ReferenceBlockStamp(
        **_build_blockstamp_data(slot_details),
        ref_slot=ref_slot,
        ref_epoch=ref_epoch
    )


def build_blockstamp(slot_details: BlockDetailsResponse):
    return BlockStamp(**_build_blockstamp_data(slot_details))


def _build_blockstamp_data(
    slot_details: BlockDetailsResponse,
) -> dict:

    execution_payload = slot_details.message.body.execution_payload

    return {
        "slot_number": SlotNumber(int(slot_details.message.slot)),
        "state_root": slot_details.message.state_root,
        "block_number": BlockNumber(int(execution_payload.block_number)),
        "block_hash": execution_payload.block_hash,
        "block_timestamp": Timestamp(int(execution_payload.timestamp))
    }
