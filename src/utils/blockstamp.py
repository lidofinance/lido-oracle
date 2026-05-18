import logging

from eth_typing import BlockNumber
from eth_utils.hexadecimal import add_0x_prefix
from web3.eth import Eth
from web3.types import Timestamp

from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.types import BlockDetailsResponse
from src.types import BlockHash, BlockStamp, EpochNumber, ReferenceBlockStamp, SlotNumber
from src.utils.slot import get_prev_non_missed_slot


logger = logging.getLogger(__name__)


def build_blockstamp(slot_details: BlockDetailsResponse) -> BlockStamp:
    """Build blockstamp from pre-ePBS block details (execution_payload must be present)."""
    execution_payload = slot_details.message.body.execution_payload
    assert execution_payload is not None, "execution_payload required; use BlockstampBuilder for post-ePBS slots"
    return BlockStamp(
        slot_number=slot_details.message.slot,
        state_root=slot_details.message.state_root,
        block_number=execution_payload.block_number,
        block_hash=BlockHash(add_0x_prefix(execution_payload.block_hash)),
        block_timestamp=execution_payload.timestamp,
    )


class BlockstampBuilder:

    def __init__(self, cc: ConsensusClient, w3_eth: Eth):
        self.cc = cc
        self.w3_eth = w3_eth

    def get_non_missed_blockstamp(
        self,
        slot: SlotNumber,
        last_finalized_slot_number: SlotNumber,
    ):
        """Get first non-missed slot header and generates blockstamp for it"""
        logger.info({'msg': f'Get Blockstamp for slot: {slot}'})
        existed_slot = get_prev_non_missed_slot(self.cc, slot, last_finalized_slot_number)
        logger.info({'msg': f'Resolved to slot: {existed_slot.message.slot}'})
        return self.build_blockstamp(existed_slot)


    def get_non_missed_reference_blockstamp(
        self,
        ref_slot: SlotNumber,
        last_finalized_slot_number: SlotNumber,
        ref_epoch: EpochNumber,
    ) -> ReferenceBlockStamp:
        """Get first non-missed slot header and generates reference blockstamp for it"""
        logger.info({'msg': f'Get Reference Blockstamp for ref slot: {ref_slot}'})
        existed_slot = get_prev_non_missed_slot(self.cc, ref_slot, last_finalized_slot_number)
        logger.info({'msg': f'Resolved to slot: {existed_slot.message.slot}'})
        return self._build_reference_blockstamp(existed_slot, ref_slot, ref_epoch)

    def _build_reference_blockstamp(
        self,
        slot_details: BlockDetailsResponse,
        ref_slot: SlotNumber,
        ref_epoch: EpochNumber,
    ) -> ReferenceBlockStamp:
        return ReferenceBlockStamp(
            **self._build_blockstamp_data(slot_details),
            ref_slot=ref_slot,
            ref_epoch=ref_epoch,
        )

    def build_blockstamp(
        self,
        slot_details: BlockDetailsResponse,
    ) -> BlockStamp:
        return BlockStamp(**self._build_blockstamp_data(slot_details))
    
    def _build_blockstamp_data(
        self,
        slot_details: BlockDetailsResponse,
    ) -> dict:
        execution_payload = slot_details.message.body.execution_payload

        if execution_payload is not None:
            return {
                "slot_number": slot_details.message.slot,
                "state_root": slot_details.message.state_root,
                "block_number": execution_payload.block_number,
                "block_hash": add_0x_prefix(execution_payload.block_hash),
                "block_timestamp": execution_payload.timestamp,
            }

        # Post-ePBS path: execution_payload absent — use state.latest_block_hash.
        # state.latest_block_hash = last *revealed* EL block (slot N-1 when CL is at slot N).
        # This guarantees deposit symmetry: its deposit_requests are already in pending_deposits.
        state = self.cc.get_state_view(
            (slot_details.message.state_root, slot_details.message.slot)
        )
        el_hash = state.latest_block_hash
        el_block = self.w3_eth.get_block(el_hash)

        logger.info({
            'msg': 'Post-ePBS blockstamp: execution_payload absent, resolved via state.latest_block_hash',
            'slot': slot_details.message.slot,
            'el_hash': el_hash,
            'el_block_number': el_block['number'],  # type: ignore[typeddict-item]
        })

        return {
            "slot_number": slot_details.message.slot,
            "state_root": slot_details.message.state_root,
            "block_number": BlockNumber(el_block["number"]),  # type: ignore[typeddict-item]
            "block_hash": add_0x_prefix(el_hash),
            "block_timestamp": Timestamp(el_block["timestamp"]),  # type: ignore[typeddict-item]
        }
