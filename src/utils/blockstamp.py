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


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GloasChild:
    """The first non-missed block after the block a blockstamp is built for (EIP-7732).

    `latest_block_hash` (read from this child's state) is the confirmed execution-layer anchor
    ("Y") for the parent block. The child is resolved once by src/utils/slot.py and passed in so
    that this module never imports slot.py (avoiding a circular import).
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


def _base_fields(
    slot_details: BlockDetailsResponse,
    cc: ConsensusClient,
    el: Eth | None,
    child: GloasChild | None,
) -> dict:
    """Resolve the five BlockStamp fields for `slot_details`, handling the EIP-7732 cases.

    - Pre-fork block (execution_payload embedded): read the anchor from the payload, as before.
    - Post-fork, child provided (report / historical): the EL anchor is the child's
      latest_block_hash resolved to a full EL block.
    - Post-fork, no child (head / finalized liveness): read this block's own latest_block_hash.
    - Post-fork, no EL client (`el is None`, performance collector): inert placeholder EL fields.
    """
    execution_payload = slot_details.message.body.execution_payload
    if execution_payload is not None:
        el_fields = _el_fields_from_payload(execution_payload)
    elif el is None:
        el_fields = dict(_PLACEHOLDER_EL_FIELDS)
    elif child is not None:
        el_fields = _el_fields_from_hash(el, child.latest_block_hash)
    else:
        own_hash = cc.get_state_latest_block_hash((slot_details.message.state_root, slot_details.message.slot))
        el_fields = _el_fields_from_hash(el, own_hash)

    return {
        "slot_number": slot_details.message.slot,
        "state_root": slot_details.message.state_root,
        **el_fields,
    }


def build_reference_blockstamp(
    slot_details: BlockDetailsResponse,
    ref_slot: SlotNumber,
    ref_epoch: EpochNumber,
    cc: ConsensusClient | None = None,
    el: Eth | None = None,
    child: GloasChild | None = None,
) -> ReferenceBlockStamp:
    base = _base_fields(slot_details, cc=cc, el=el, child=child)  # type: ignore[arg-type]

    child_state_root: StateRoot | None = None
    child_slot: SlotNumber | None = None
    withdrawal_correction_needed = False
    if child is not None:
        child_state_root = child.state_root
        child_slot = child.slot
        # ref_slot's own payload was confirmed full iff the child's latest_block_hash equals the
        # block hash ref_slot's builder committed to in its bid. If not confirmed full, CL balances
        # are already reduced by payload_expected_withdrawals but the EL has not credited them yet.
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


def build_blockstamp(
    slot_details: BlockDetailsResponse,
    cc: ConsensusClient | None = None,
    el: Eth | None = None,
    child: GloasChild | None = None,
) -> BlockStamp:
    return BlockStamp(**_base_fields(slot_details, cc=cc, el=el, child=child))  # type: ignore[arg-type]


def get_blockstamp_by_state(cc: ConsensusClient, state: LiteralState, el: Eth | None = None) -> BlockStamp:
    """Fetch the block for the given chain state and build a BlockStamp from it.

    This is the liveness path (head / finalized): the block has no finalized child to read the
    execution anchor from, so post-fork the anchor comes from the block's own latest_block_hash.
    """
    block_root = cc.get_block_root(state).root
    block_details = cc.get_block_details(block_root)
    bs = build_blockstamp(block_details, cc=cc, el=el)
    logger.info({'msg': f'Fetch {state} blockstamp.', 'value': asdict(bs)})
    ORACLE_SLOT_NUMBER.labels(state).set(bs.slot_number)
    ORACLE_BLOCK_NUMBER.labels(state).set(bs.block_number)
    return bs
