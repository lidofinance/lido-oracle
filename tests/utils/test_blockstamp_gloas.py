"""Unit tests for EIP-7732 (Gloas) blockstamp construction.

Post-fork a blockstamp for slot N is built from N's child (the first non-missed block after N), and
its execution anchor comes from that child's payload bid. These cover the anchor, the CL-only
placeholder path, the pre-fork regression path and the forward resolver.
"""

from http import HTTPStatus
from unittest.mock import Mock

import pytest
from eth_utils import add_0x_prefix

from src.providers.consensus.types import ExecutionPayloadBid, SignedExecutionPayloadBid
from src.providers.http_provider import NotOkResponse
from src.types import BlockHash, EpochNumber, SlotNumber
from src.utils.blockstamp import (
    MissingExecutionAnchor,
    build_blockstamp,
    get_blockstamp,
    get_blockstamp_by_state,
    get_reference_blockstamp,
)
from src.utils.slot import ChildSlotNotFinalized, get_next_non_missed_slot
from tests.factory.configs import BlockDetailsResponseFactory
from tests.factory.consensus import BlockHeaderFullResponseFactory


ANCHOR_HASH = "0xaaaa"


def _post_fork_details(slot: int, parent_block_hash: str | None = ANCHOR_HASH):
    """A post-EIP-7732 block: no embedded execution_payload, bid instead."""
    details = BlockDetailsResponseFactory.build(message={"slot": slot})
    details.message.body.execution_payload = None
    details.message.body.signed_execution_payload_bid = (
        None
        if parent_block_hash is None
        else SignedExecutionPayloadBid(message=ExecutionPayloadBid(parent_block_hash=BlockHash(parent_block_hash)))
    )
    return details


@pytest.fixture
def el():
    return Mock(get_block=Mock(return_value={"number": 999, "timestamp": 424242}))


@pytest.mark.unit
class TestExecutionAnchorResolution:
    def test_build_blockstamp__pre_fork__uses_embedded_payload(self, el):
        # Arrange: pre-fork block carries an embedded execution payload.
        details = BlockDetailsResponseFactory.build(message={"slot": 100})
        payload = details.message.body.execution_payload

        # Act
        bs = build_blockstamp(details, el)

        # Assert: identical to the legacy behavior, the execution client is never consulted.
        assert bs.block_hash == add_0x_prefix(payload.block_hash)
        assert bs.block_number == payload.block_number
        assert bs.block_timestamp == payload.timestamp
        el.get_block.assert_not_called()

    def test_build_blockstamp__post_fork__anchors_on_bid_parent_block_hash(self, el):
        # Arrange: post-fork the anchor is the last payload applied to this block's state, which the
        # block's own bid carries - no beacon state is downloaded for it.
        details = _post_fork_details(slot=100)

        # Act
        bs = build_blockstamp(details, el)

        # Assert
        assert bs.slot_number == SlotNumber(100)
        assert bs.state_root == details.message.state_root
        assert bs.block_hash == add_0x_prefix(ANCHOR_HASH)
        assert bs.block_number == 999
        assert bs.block_timestamp == 424242
        el.get_block.assert_called_once_with(BlockHash(ANCHOR_HASH))

    def test_build_blockstamp__block_without_bid__raises(self, el):
        # Arrange: a post-fork block with no resolvable execution anchor at all.
        details = _post_fork_details(slot=100, parent_block_hash=None)

        # Act / Assert
        with pytest.raises(MissingExecutionAnchor):
            build_blockstamp(details, el)


@pytest.mark.unit
class TestAnchorBlockSelection:
    @pytest.fixture
    def resolvers(self, monkeypatch):
        """Patch both slot resolvers and hand the mocks back, so tests can assert which ran."""
        prev, nxt = Mock(), Mock()
        monkeypatch.setattr('src.utils.blockstamp.get_prev_non_missed_slot', prev)
        monkeypatch.setattr('src.utils.blockstamp.get_next_non_missed_slot', nxt)
        return prev, nxt

    def test_get_reference_blockstamp__post_fork__built_from_ref_slot_child(self, el, resolvers):
        # Arrange: the block at ref_slot 99 has no embedded payload, its child is slot 101.
        prev, nxt = resolvers
        prev.return_value = _post_fork_details(slot=99)
        nxt.return_value = _post_fork_details(slot=101)

        # Act
        bs = get_reference_blockstamp(
            Mock(), ref_slot=SlotNumber(99), last_finalized_slot_number=SlotNumber(200), ref_epoch=EpochNumber(3), el=el
        )

        # Assert: the report's own block sits after the ref slot.
        assert bs.ref_slot == SlotNumber(99)
        assert bs.ref_epoch == EpochNumber(3)
        assert bs.slot_number == SlotNumber(101)
        assert bs.state_root == nxt.return_value.message.state_root
        assert bs.block_hash == add_0x_prefix(ANCHOR_HASH)

    def test_get_reference_blockstamp__pre_fork__built_from_last_block_at_or_before_ref_slot(self, el, resolvers):
        # Arrange: the block at (or before) ref_slot embeds its execution payload.
        prev, nxt = resolvers
        prev.return_value = BlockDetailsResponseFactory.build(message={"slot": 98})

        # Act
        bs = get_reference_blockstamp(
            Mock(), ref_slot=SlotNumber(99), last_finalized_slot_number=SlotNumber(200), ref_epoch=EpochNumber(3), el=el
        )

        # Assert: no child lookup happens pre-fork.
        assert bs.slot_number == SlotNumber(98)
        assert bs.ref_slot == SlotNumber(99)
        nxt.assert_not_called()

    def test_get_blockstamp__post_fork__built_from_child_too(self, el, resolvers):
        # Arrange: plain blockstamps follow the same rule so that a past report's anchor block
        # resolves to the same execution block that report used.
        prev, nxt = resolvers
        prev.return_value = _post_fork_details(slot=99)
        nxt.return_value = _post_fork_details(slot=101)

        # Act
        bs = get_blockstamp(Mock(), SlotNumber(99), last_finalized_slot_number=SlotNumber(200), el=el)

        # Assert
        assert bs.slot_number == SlotNumber(101)
        assert bs.block_hash == add_0x_prefix(ANCHOR_HASH)
        nxt.assert_called_once_with(prev.call_args.args[0], SlotNumber(99), SlotNumber(200))

    def test_get_blockstamp_by_state__post_fork_head__anchors_on_own_bid(self, el):
        # Arrange: the chain tip has no child, so it is its own anchor block.
        details = _post_fork_details(slot=100)
        cc = Mock(get_block_details=Mock(return_value=details))

        # Act
        bs = get_blockstamp_by_state(cc, 'head', el)

        # Assert: no beacon state is downloaded on the per-cycle liveness path.
        cc.get_block_root.assert_called_once_with('head')
        cc.get_state_view.assert_not_called()
        assert bs.slot_number == SlotNumber(100)
        assert bs.block_hash == add_0x_prefix(ANCHOR_HASH)


@pytest.mark.unit
class TestGetNextNonMissedSlot:
    def test_get_next_non_missed_slot__returns_first_block_after_slot(self):
        # Arrange: slot+1 exists.
        child_slot = 101
        header = BlockHeaderFullResponseFactory.build(data={"header": {"message": {"slot": child_slot}}})
        details = BlockDetailsResponseFactory.build(message={"slot": child_slot})
        cc = Mock(get_block_header=Mock(return_value=header), get_block_details=Mock(return_value=details))

        # Act
        result = get_next_non_missed_slot(cc, SlotNumber(100), last_finalized_slot_number=SlotNumber(200))

        # Assert
        assert result.message.slot == child_slot
        # forward scan starts at slot + 1
        cc.get_block_header.assert_called_once_with(SlotNumber(101))

    def test_get_next_non_missed_slot__skips_missed_child_slots(self):
        # Arrange: 101 and 102 missed, 103 exists.
        def get_block_header(state_id):
            if state_id < 103:
                raise NotOkResponse("missed", status=HTTPStatus.NOT_FOUND, text="not found")
            return BlockHeaderFullResponseFactory.build(data={"header": {"message": {"slot": 103}}})

        cc = Mock(
            get_block_header=Mock(side_effect=get_block_header),
            get_block_details=Mock(return_value=BlockDetailsResponseFactory.build(message={"slot": 103})),
        )

        # Act
        result = get_next_non_missed_slot(cc, SlotNumber(100), last_finalized_slot_number=SlotNumber(200))

        # Assert
        assert result.message.slot == 103

    def test_get_next_non_missed_slot__no_finalized_child__raises(self):
        # Arrange: the slot is at (or after) the last finalized slot, so it has no finalized child.
        cc = Mock()

        # Act / Assert
        with pytest.raises(ChildSlotNotFinalized):
            get_next_non_missed_slot(cc, SlotNumber(200), last_finalized_slot_number=SlotNumber(200))
