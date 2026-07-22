import logging
from dataclasses import asdict, dataclass

from eth_typing import BlockNumber, HexStr
from eth_utils.hexadecimal import add_0x_prefix
from web3.eth import Eth
from web3.types import Timestamp

from src.metrics.prometheus.basic import ORACLE_BLOCK_NUMBER, ORACLE_SLOT_NUMBER
from src.providers.consensus.client import ConsensusClient, LiteralState
from src.providers.consensus.types import BlockDetailsResponse
from src.types import BlockHash, BlockStamp, EpochNumber, ReferenceBlockStamp, SlotNumber, StateRoot
from src.utils.slot import get_next_non_missed_slot, get_prev_non_missed_slot


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GloasChild:
    """The first non-missed block after the block a blockstamp is built for (EIP-7732).

    `latest_block_hash` (read from this child's state) is the confirmed execution-layer anchor
    ("Y") for the parent block.
    """

    state_root: StateRoot
    slot: SlotNumber
    latest_block_hash: BlockHash


# Placeholder execution-layer fields for CL-only consumers (the performance collector) that build
# blockstamps without an execution client. Such consumers read only slot_number / state_root, never
# these fields; post-fork we cannot resolve a real EL anchor without an EL client.
_PLACEHOLDER_EL_FIELDS: dict = {
    "block_number": BlockNumber(0),
    "block_hash": BlockHash(add_0x_prefix(HexStr(''))),
    "block_timestamp": Timestamp(0),
}


def _hashes_equal(a: BlockHash, b: BlockHash) -> bool:
    return add_0x_prefix(a).lower() == add_0x_prefix(b).lower()


def _el_fields_from_payload(execution_payload) -> dict:
    return {
        "block_number": execution_payload.block_number,
        "block_hash": add_0x_prefix(execution_payload.block_hash),
        "block_timestamp": execution_payload.timestamp,
    }


def _el_fields_from_hash(el: Eth, el_block_hash: BlockHash) -> dict:
    block = el.get_block(el_block_hash)
    return {
        "block_number": BlockNumber(block["number"]),  # type: ignore[typeddict-item]
        "block_hash": add_0x_prefix(el_block_hash),
        "block_timestamp": Timestamp(block["timestamp"]),  # type: ignore[typeddict-item]
    }


class BlockstampBuilder:
    """Builds BlockStamps, resolving the execution-layer anchor per the EIP-7732 rules.

    Holds the consensus client and (optionally) the execution client so callers don't thread them
    through every call. Under Gloas a block no longer embeds its execution payload, so the EL anchor
    is resolved from:
      - the block's own embedded payload (pre-fork), or
      - ref_slot's child state `latest_block_hash` (report / historical), or
      - the block's own state `latest_block_hash` (head / finalized liveness), or
      - inert placeholders when no execution client is supplied (CL-only performance collector).
    """

    def __init__(self, cc: ConsensusClient, el: Eth | None = None):
        self.cc = cc
        self.el = el

    def get_blockstamp(self, slot: SlotNumber, last_finalized_slot_number: SlotNumber) -> BlockStamp:
        """Resolve the first non-missed block at/before `slot` and build a BlockStamp for it."""
        logger.info({'msg': f'Get Blockstamp for slot: {slot}'})
        existed_slot = get_prev_non_missed_slot(self.cc, slot, last_finalized_slot_number)
        logger.info({'msg': f'Resolved to slot: {existed_slot.message.slot}'})
        child = self._resolve_gloas_child(existed_slot, last_finalized_slot_number)
        return self.build_blockstamp(existed_slot, child)

    def get_reference_blockstamp(
        self,
        ref_slot: SlotNumber,
        last_finalized_slot_number: SlotNumber,
        ref_epoch: EpochNumber,
    ) -> ReferenceBlockStamp:
        """Resolve the first non-missed block at/before `ref_slot` and build a ReferenceBlockStamp."""
        logger.info({'msg': f'Get Reference Blockstamp for ref slot: {ref_slot}'})
        existed_slot = get_prev_non_missed_slot(self.cc, ref_slot, last_finalized_slot_number)
        logger.info({'msg': f'Resolved to slot: {existed_slot.message.slot}'})
        child = self._resolve_gloas_child(existed_slot, last_finalized_slot_number)
        return self.build_reference_blockstamp(existed_slot, ref_slot, ref_epoch, child)

    def get_blockstamp_by_state(self, state: LiteralState) -> BlockStamp:
        """Fetch the block for the given chain state (head/finalized/...) and build a BlockStamp.

        This is the liveness path: the block has no finalized child to read the execution anchor
        from, so post-fork the anchor comes from the block's own latest_block_hash.
        """
        block_root = self.cc.get_block_root(state).root
        block_details = self.cc.get_block_details(block_root)
        bs = self.build_blockstamp(block_details)
        logger.info({'msg': f'Fetch {state} blockstamp.', 'value': asdict(bs)})
        ORACLE_SLOT_NUMBER.labels(state).set(bs.slot_number)
        ORACLE_BLOCK_NUMBER.labels(state).set(bs.block_number)
        return bs

    def build_blockstamp(self, slot_details: BlockDetailsResponse, child: GloasChild | None = None) -> BlockStamp:
        return BlockStamp(**self._base_fields(slot_details, child))

    def build_reference_blockstamp(
        self,
        slot_details: BlockDetailsResponse,
        ref_slot: SlotNumber,
        ref_epoch: EpochNumber,
        child: GloasChild | None = None,
    ) -> ReferenceBlockStamp:
        base = self._base_fields(slot_details, child)

        child_state_root: StateRoot | None = None
        child_slot: SlotNumber | None = None
        withdrawal_correction_needed = False
        if child is not None:
            child_state_root = child.state_root
            child_slot = child.slot
            # ref_slot's own payload was confirmed full iff the child's latest_block_hash equals the
            # block hash ref_slot's builder committed to in its bid. If not confirmed full, CL
            # balances are already reduced by payload_expected_withdrawals but the EL has not credited
            # them yet.
            bid = slot_details.message.body.signed_execution_payload_bid
            committed = bid.message.block_hash if bid is not None else None
            withdrawal_correction_needed = committed is None or not _hashes_equal(child.latest_block_hash, committed)

        return ReferenceBlockStamp(
            **base,
            ref_slot=ref_slot,
            ref_epoch=ref_epoch,
            child_state_root=child_state_root,
            child_slot=child_slot,
            withdrawal_correction_needed=withdrawal_correction_needed,
        )

    def _resolve_gloas_child(
        self, slot_details: BlockDetailsResponse, last_finalized_slot_number: SlotNumber
    ) -> GloasChild | None:
        """Resolve the child anchor for a post-EIP-7732 block; None for pre-fork blocks.

        Pre-fork blocks embed their execution payload, so no child lookup is needed and behavior is
        unchanged. Post-fork the child's state supplies the execution anchor and pending_deposits.
        """
        if slot_details.message.body.execution_payload is not None:
            return None
        child = get_next_non_missed_slot(self.cc, slot_details.message.slot, last_finalized_slot_number)
        child_state = self.cc.get_state_view((child.message.state_root, child.message.slot))
        return GloasChild(
            state_root=child.message.state_root,
            slot=child.message.slot,
            latest_block_hash=child_state.latest_block_hash,
        )

    def _base_fields(self, slot_details: BlockDetailsResponse, child: GloasChild | None) -> dict:
        """Resolve the five BlockStamp fields, handling the EIP-7732 execution-anchor cases."""
        execution_payload = slot_details.message.body.execution_payload
        if execution_payload is not None:
            el_fields = _el_fields_from_payload(execution_payload)
        elif self.el is None:
            el_fields = dict(_PLACEHOLDER_EL_FIELDS)
        elif child is not None:
            el_fields = _el_fields_from_hash(self.el, child.latest_block_hash)
        else:
            own_hash = self.cc.get_state_latest_block_hash((slot_details.message.state_root, slot_details.message.slot))
            el_fields = _el_fields_from_hash(self.el, own_hash)

        return {
            "slot_number": slot_details.message.slot,
            "state_root": slot_details.message.state_root,
            **el_fields,
        }
