"""Unit tests for EIP-7732 (Gloas) blockstamp construction.

Post-fork a blockstamp for slot N is built from N's child (the first non-missed block after N).
Report blockstamps take the execution anchor from that child's beacon state; liveness blockstamps,
which never read CL state, take the equal value from the child's execution payload bid. These cover
both sources, the CL-only placeholder path, the pre-fork regression path and the forward resolver.
"""

from http import HTTPStatus
from unittest.mock import Mock

import pytest
from eth_utils import add_0x_prefix

from src.providers.consensus.types import ExecutionPayloadBid, SignedExecutionPayloadBid
from src.providers.http_provider import NotOkResponse
from src.types import BlockHash, EpochNumber, SlotNumber
from src.utils.blockstamp import BlockstampBuilder, MissingExecutionAnchor
from src.utils.slot import ChildSlotNotFinalized, get_next_non_missed_slot
from tests.factory.configs import BlockDetailsResponseFactory
from tests.factory.consensus import BlockHeaderFullResponseFactory


ANCHOR_HASH = "0xaaaa"


def _cc(**kwargs) -> Mock:
    """Consensus client whose state reports ANCHOR_HASH as its latest_block_hash."""
    return Mock(get_state_view=Mock(return_value=Mock(latest_block_hash=BlockHash(ANCHOR_HASH))), **kwargs)


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
        bs = BlockstampBuilder(Mock(), el).build_blockstamp(details)

        # Assert: identical to the legacy behavior, the execution client is never consulted.
        assert bs.block_hash == add_0x_prefix(payload.block_hash)
        assert bs.block_number == payload.block_number
        assert bs.block_timestamp == payload.timestamp
        el.get_block.assert_not_called()

    def test_build_blockstamp__post_fork_report__anchors_on_state_latest_block_hash(self, el):
        # Arrange: report blockstamps read the anchor from the beacon state.
        details = _post_fork_details(slot=100, parent_block_hash="0xdead")
        cc = _cc()

        # Act
        bs = BlockstampBuilder(cc, el).build_blockstamp(details)

        # Assert: the state wins, addressed by (state_root, slot) so it shares the report's cache entry.
        cc.get_state_view.assert_called_once_with((details.message.state_root, SlotNumber(100)))
        assert bs.slot_number == SlotNumber(100)
        assert bs.state_root == details.message.state_root
        assert bs.block_hash == add_0x_prefix(ANCHOR_HASH)
        assert bs.block_number == 999
        assert bs.block_timestamp == 424242
        el.get_block.assert_called_once_with(BlockHash(ANCHOR_HASH))

    def test_build_blockstamp__post_fork_liveness__anchors_on_bid_parent_block_hash(self, el):
        # Arrange: liveness blockstamps must not download a beacon state, so they opt out.
        details = _post_fork_details(slot=100)
        cc = _cc()

        # Act
        bs = BlockstampBuilder(cc, el).build_blockstamp(details, read_anchor_from_state=False)

        # Assert: bid.parent_block_hash == state.latest_block_hash by consensus rule.
        cc.get_state_view.assert_not_called()
        assert bs.block_hash == add_0x_prefix(ANCHOR_HASH)
        el.get_block.assert_called_once_with(BlockHash(ANCHOR_HASH))

    def test_build_blockstamp__report_anchor_missing_from_state__raises(self, el):
        # Arrange: a state with no latest_block_hash (pre-fork default) is not a usable anchor.
        details = _post_fork_details(slot=100)
        cc = Mock(get_state_view=Mock(return_value=Mock(latest_block_hash="")))

        # Act / Assert
        with pytest.raises(MissingExecutionAnchor):
            BlockstampBuilder(cc, el).build_blockstamp(details)

    def test_build_blockstamp__no_execution_client__placeholder_fields(self):
        # Arrange: CL-only consumer (performance collector) has no execution client.
        details = _post_fork_details(slot=100)

        # Act
        bs = BlockstampBuilder(_cc(), None).build_blockstamp(details)

        # Assert: EL fields are inert placeholders; CL fields are correct.
        assert bs.slot_number == SlotNumber(100)
        assert bs.state_root == details.message.state_root
        assert bs.block_number == 0

    def test_build_blockstamp__liveness_block_without_bid__raises(self, el):
        # Arrange: a block with no resolvable execution anchor at all.
        details = _post_fork_details(slot=100, parent_block_hash=None)

        # Act / Assert
        with pytest.raises(MissingExecutionAnchor):
            BlockstampBuilder(_cc(), el).build_blockstamp(details, read_anchor_from_state=False)


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
        bs = BlockstampBuilder(_cc(), el).get_reference_blockstamp(
            ref_slot=SlotNumber(99), last_finalized_slot_number=SlotNumber(200), ref_epoch=EpochNumber(3)
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
        bs = BlockstampBuilder(_cc(), el).get_reference_blockstamp(
            ref_slot=SlotNumber(99), last_finalized_slot_number=SlotNumber(200), ref_epoch=EpochNumber(3)
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
        bs = BlockstampBuilder(_cc(), el).get_blockstamp(SlotNumber(99), last_finalized_slot_number=SlotNumber(200))

        # Assert
        assert bs.slot_number == SlotNumber(101)
        assert bs.block_hash == add_0x_prefix(ANCHOR_HASH)
        nxt.assert_called_once_with(prev.call_args.args[0], SlotNumber(99), SlotNumber(200))

    def test_get_blockstamp_by_state__post_fork_head__anchors_on_own_bid(self, el):
        # Arrange: the chain tip has no child, so it is its own anchor block.
        details = _post_fork_details(slot=100)
        cc = _cc(get_block_details=Mock(return_value=details))

        # Act
        bs = BlockstampBuilder(cc, el).get_blockstamp_by_state('head')

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

    def test_get_next_non_missed_slot__child_past_last_finalized__raises(self):
        # Arrange: a resolver that hands back a header beyond the finalized slot must not be
        # trusted - a report may only ever be built on a finalized block.
        header = BlockHeaderFullResponseFactory.build(data={"header": {"message": {"slot": 500}}})
        cc = Mock(get_block_header=Mock(return_value=header), get_block_details=Mock())

        # Act / Assert
        with pytest.raises(ChildSlotNotFinalized, match="past the last finalized slot"):
            get_next_non_missed_slot(cc, SlotNumber(100), last_finalized_slot_number=SlotNumber(200))
        cc.get_block_details.assert_not_called()

    def test_get_next_non_missed_slot__no_finalized_child__raises(self):
        # Arrange: the slot is at (or after) the last finalized slot, so it has no finalized child.
        cc = Mock()

        # Act / Assert
        with pytest.raises(ChildSlotNotFinalized):
            get_next_non_missed_slot(cc, SlotNumber(200), last_finalized_slot_number=SlotNumber(200))
