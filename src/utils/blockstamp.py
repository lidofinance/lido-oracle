import logging
from dataclasses import asdict

from eth_typing import BlockNumber, HexStr
from eth_utils.hexadecimal import add_0x_prefix
from web3.eth import Eth
from web3.types import Timestamp

from src.metrics.prometheus.basic import ORACLE_BLOCK_NUMBER, ORACLE_SLOT_NUMBER
from src.providers.consensus.client import ConsensusClient, LiteralState
from src.providers.consensus.types import BlockDetailsResponse
from src.types import BlockHash, BlockStamp, EpochNumber, ReferenceBlockStamp, SlotNumber
from src.utils.slot import get_next_non_missed_slot, get_prev_non_missed_slot


logger = logging.getLogger(__name__)


class MissingExecutionAnchor(Exception):
    """Raised when a post-EIP-7732 block's execution-layer anchor cannot be resolved: neither the
    beacon state's `latest_block_hash` nor the block's signed execution payload bid is readable."""


# Placeholder execution-layer fields for CL-only consumers (the performance collector) that build
# blockstamps without an execution client. Such consumers read only slot_number / state_root, never
# these fields; post-fork we cannot resolve a real EL anchor without an EL client.
_PLACEHOLDER_EL_FIELDS: dict = {
    "block_number": BlockNumber(0),
    "block_hash": BlockHash(add_0x_prefix(HexStr(''))),
    "block_timestamp": Timestamp(0),
}


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
    through every call.

    Before Glamsterdam a beacon block embeds its own execution payload, so a blockstamp for slot N
    is built from the last non-missed block at or before N and the payload found in its body.

    After Glamsterdam (EIP-7732) the payload is revealed separately and is only applied to the
    beacon state while processing the *next* block. A blockstamp for slot N is therefore built from
    N's child — the first non-missed block after N — whose state is the earliest one where N's
    execution payload, deposits and withdrawals are all settled. The child's execution anchor is its
    `state.latest_block_hash`: N's own execution block when N's payload was revealed, an earlier one
    when it was withheld.

    Blockstamps that a report is computed on read that anchor from the beacon state itself. It costs
    nothing there — the report reads the very same state for validators and pending_deposits, and
    `ConsensusClient.get_state_view` keys its cache on `(state_root, slot)` so both reads hit one
    entry.

    Liveness blockstamps (head/finalized, rebuilt every daemon cycle) never read CL state — they
    only supply a block hash for `eth_call`s — so downloading a multi-gigabyte state for them is not
    an option. They take the anchor from the block's own bid instead:
    `process_execution_payload_bid` asserts `bid.parent_block_hash == state.latest_block_hash` for
    every block, so the block body carries the same value for free.
    """

    def __init__(self, cc: ConsensusClient, el: Eth | None = None):
        self.cc = cc
        self.el = el

    def get_blockstamp(self, slot: SlotNumber, last_finalized_slot_number: SlotNumber) -> BlockStamp:
        """Build a BlockStamp for `slot` from its anchor block."""
        logger.info({'msg': f'Get Blockstamp for slot: {slot}'})
        anchor = self._resolve_anchor_block(slot, last_finalized_slot_number)
        logger.info({'msg': f'Resolved to slot: {anchor.message.slot}'})
        return self.build_blockstamp(anchor)

    def get_reference_blockstamp(
        self,
        ref_slot: SlotNumber,
        last_finalized_slot_number: SlotNumber,
        ref_epoch: EpochNumber,
    ) -> ReferenceBlockStamp:
        """Build a ReferenceBlockStamp for `ref_slot` from its anchor block."""
        logger.info({'msg': f'Get Reference Blockstamp for ref slot: {ref_slot}'})
        anchor = self._resolve_anchor_block(ref_slot, last_finalized_slot_number)
        logger.info({'msg': f'Resolved to slot: {anchor.message.slot}'})
        return self.build_reference_blockstamp(anchor, ref_slot, ref_epoch)

    def get_blockstamp_by_state(self, state: LiteralState) -> BlockStamp:
        """Fetch the block for the given chain state (head/finalized/...) and build a BlockStamp.

        This is the liveness path: the chain tip has no child yet, so the blockstamp is built from
        the block itself. It is also the one caller that cannot read CL state for its anchor — see
        `_anchor_hash` — so it opts out.
        """
        block_root = self.cc.get_block_root(state).root
        block_details = self.cc.get_block_details(block_root)
        bs = self.build_blockstamp(block_details, read_anchor_from_state=False)
        logger.info({'msg': f'Fetch {state} blockstamp.', 'value': asdict(bs)})
        ORACLE_SLOT_NUMBER.labels(state).set(bs.slot_number)
        ORACLE_BLOCK_NUMBER.labels(state).set(bs.block_number)
        return bs

    def build_blockstamp(
        self, slot_details: BlockDetailsResponse, *, read_anchor_from_state: bool = True
    ) -> BlockStamp:
        return BlockStamp(**self._base_fields(slot_details, read_anchor_from_state))

    def build_reference_blockstamp(
        self,
        slot_details: BlockDetailsResponse,
        ref_slot: SlotNumber,
        ref_epoch: EpochNumber,
        *,
        read_anchor_from_state: bool = True,
    ) -> ReferenceBlockStamp:
        return ReferenceBlockStamp(
            **self._base_fields(slot_details, read_anchor_from_state),
            ref_slot=ref_slot,
            ref_epoch=ref_epoch,
        )

    def _resolve_anchor_block(self, slot: SlotNumber, last_finalized_slot_number: SlotNumber) -> BlockDetailsResponse:
        """The beacon block a blockstamp for `slot` is built from.

        Pre-fork that is the last non-missed block at or before `slot`; post-fork it is `slot`'s
        child, the first non-missed block after it. See the class docstring for why.

        Which fork applies is read off the block itself — an embedded execution payload means
        pre-EIP-7732 — rather than from a fork epoch in the beacon config. The block shape is
        unambiguous, while a config key that is missing or renamed would silently select the wrong
        branch. Pre-fork this costs nothing: the block we probe is the one we return.
        """
        block = get_prev_non_missed_slot(self.cc, slot, last_finalized_slot_number)
        if block.message.body.execution_payload is not None:
            return block
        return get_next_non_missed_slot(self.cc, slot, last_finalized_slot_number)

    def _base_fields(self, slot_details: BlockDetailsResponse, read_anchor_from_state: bool) -> dict:
        """Resolve the five BlockStamp fields, handling the EIP-7732 execution-anchor cases."""
        return {
            "slot_number": slot_details.message.slot,
            "state_root": slot_details.message.state_root,
            **self._el_fields(slot_details, read_anchor_from_state),
        }

    def _el_fields(self, slot_details: BlockDetailsResponse, read_anchor_from_state: bool) -> dict:
        if slot_details.message.body.execution_payload is not None:
            # Pre-EIP-7732: the block embeds the execution payload it was built with.
            return _el_fields_from_payload(slot_details.message.body.execution_payload)

        if self.el is None:
            # CL-only consumer: no execution client to resolve the anchor block with.
            return dict(_PLACEHOLDER_EL_FIELDS)

        return _el_fields_from_hash(self.el, self._anchor_hash(slot_details, read_anchor_from_state))

    def _anchor_hash(self, slot_details: BlockDetailsResponse, read_from_state: bool) -> BlockHash:
        """The post-EIP-7732 execution-layer anchor of `slot_details`.

        `state.latest_block_hash` is the anchor, and it is what every blockstamp a report is
        computed on uses. Reading it costs a whole beacon state, so the one caller that would pay
        that per daemon cycle without needing the state for anything else — the head/finalized
        liveness stamp — reads the identical value out of the block's bid instead. See the class
        docstring for why the two agree.
        """
        slot = slot_details.message.slot

        if read_from_state:
            anchor = self.cc.get_state_view((slot_details.message.state_root, slot)).latest_block_hash
            if not anchor:
                raise MissingExecutionAnchor(f'State at slot [{slot}] has no latest_block_hash.')
            return anchor

        bid = slot_details.message.body.signed_execution_payload_bid
        if bid is None:
            raise MissingExecutionAnchor(
                f'Block at slot [{slot}] has neither an execution payload nor an execution payload bid.'
            )
        return bid.message.parent_block_hash
