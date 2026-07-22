"""Unit tests for EIP-7732 (Gloas) blockstamp construction.

These cover the three post-fork execution-anchor resolution modes (child-based, own-state,
CL-only placeholder), the pre-fork regression path, and the child-slot forward resolver.
"""

from http import HTTPStatus
from unittest.mock import Mock

import pytest
from eth_utils import add_0x_prefix

from src.providers.consensus.types import ExecutionPayloadBid, SignedExecutionPayloadBid
from src.providers.http_provider import NotOkResponse
from src.types import BlockHash, EpochNumber, SlotNumber, StateRoot
from src.utils.blockstamp import BlockstampBuilder, GloasChild
from src.utils.slot import ChildSlotNotFinalized, get_next_non_missed_slot
from tests.factory.configs import BlockDetailsResponseFactory
from tests.factory.consensus import BlockHeaderFullResponseFactory


def _post_fork_details(slot: int, committed_block_hash: str | None = None):
    """A post-EIP-7732 block: no embedded execution_payload, optional builder bid commitment."""
    details = BlockDetailsResponseFactory.build(message={"slot": slot})
    details.message.body.execution_payload = None
    if committed_block_hash is not None:
        details.message.body.signed_execution_payload_bid = SignedExecutionPayloadBid(
            message=ExecutionPayloadBid(block_hash=BlockHash(committed_block_hash))
        )
    else:
        details.message.body.signed_execution_payload_bid = None
    return details


@pytest.fixture
def el():
    return Mock(get_block=Mock(return_value={"number": 999, "timestamp": 424242}))


@pytest.mark.unit
class TestBuildReferenceBlockstampGloas:
    def test_build_reference_blockstamp__pre_fork__no_child_no_correction(self):
        # Arrange: pre-fork block carries an embedded execution payload.
        details = BlockDetailsResponseFactory.build(message={"slot": 100})
        payload = details.message.body.execution_payload

        # Act
        bs = BlockstampBuilder(Mock()).build_reference_blockstamp(
            details, ref_slot=SlotNumber(100), ref_epoch=EpochNumber(3)
        )

        # Assert: identical to the legacy behavior, no Gloas fields set.
        assert bs.block_hash == add_0x_prefix(payload.block_hash)
        assert bs.block_number == payload.block_number
        assert bs.child_state_root is None
        assert bs.child_slot is None
        assert bs.withdrawal_correction_needed is False

    def test_build_reference_blockstamp__payload_confirmed_full__no_correction(self, el):
        # Arrange: child's latest_block_hash equals the hash ref_slot's builder committed to.
        confirmed = "0xaaaa"
        details = _post_fork_details(slot=100, committed_block_hash=confirmed)
        child = GloasChild(
            state_root=StateRoot("0xchildstate"), slot=SlotNumber(101), latest_block_hash=BlockHash(confirmed)
        )

        # Act
        bs = BlockstampBuilder(Mock(), el).build_reference_blockstamp(
            details, ref_slot=SlotNumber(100), ref_epoch=EpochNumber(3), child=child
        )

        # Assert
        assert bs.block_hash == add_0x_prefix(confirmed)
        assert bs.block_number == 999
        assert bs.block_timestamp == 424242
        assert bs.child_state_root == StateRoot("0xchildstate")
        assert bs.child_slot == SlotNumber(101)
        assert bs.withdrawal_correction_needed is False
        el.get_block.assert_called_once_with(BlockHash(confirmed))

    def test_build_reference_blockstamp__payload_withheld__correction_needed(self, el):
        # Arrange: child's latest_block_hash is an earlier block, not ref_slot's committed one.
        details = _post_fork_details(slot=100, committed_block_hash="0xaaaa")
        child = GloasChild(
            state_root=StateRoot("0xchildstate"), slot=SlotNumber(101), latest_block_hash=BlockHash("0xbbbb")
        )

        # Act
        bs = BlockstampBuilder(Mock(), el).build_reference_blockstamp(
            details, ref_slot=SlotNumber(100), ref_epoch=EpochNumber(3), child=child
        )

        # Assert: Y != committed -> the report must add withdrawals back.
        assert bs.block_hash == add_0x_prefix("0xbbbb")
        assert bs.withdrawal_correction_needed is True

    def test_build_reference_blockstamp__missing_bid__correction_needed(self, el):
        # Arrange: post-fork block with no readable bid -> cannot prove the payload was full.
        details = _post_fork_details(slot=100, committed_block_hash=None)
        child = GloasChild(
            state_root=StateRoot("0xchildstate"), slot=SlotNumber(101), latest_block_hash=BlockHash("0xbbbb")
        )

        # Act
        bs = BlockstampBuilder(Mock(), el).build_reference_blockstamp(
            details, ref_slot=SlotNumber(100), ref_epoch=EpochNumber(3), child=child
        )

        # Assert: default to the conservative "correction needed" side.
        assert bs.withdrawal_correction_needed is True


@pytest.mark.unit
class TestBuildBlockstampGloas:
    def test_build_blockstamp__own_state_mode__uses_state_latest_block_hash(self, el):
        # Arrange: no child (head/finalized liveness) -> read the block's own latest_block_hash.
        details = _post_fork_details(slot=100)
        cc = Mock(get_state_latest_block_hash=Mock(return_value=BlockHash("0xownhash")))

        # Act
        bs = BlockstampBuilder(cc, el).build_blockstamp(details, child=None)

        # Assert
        cc.get_state_latest_block_hash.assert_called_once()
        assert bs.block_hash == add_0x_prefix("0xownhash")
        assert bs.block_number == 999

    def test_build_blockstamp__collector_no_el__placeholder_fields(self):
        # Arrange: CL-only consumer (performance collector) has no execution client.
        details = _post_fork_details(slot=100)

        # Act
        bs = BlockstampBuilder(Mock(), None).build_blockstamp(details, child=None)

        # Assert: EL fields are inert placeholders; CL fields are correct.
        assert bs.slot_number == SlotNumber(100)
        assert bs.state_root == details.message.state_root
        assert bs.block_number == 0

    def test_get_blockstamp_by_state__post_fork_head__resolves_via_own_state(self, el):
        # Arrange
        details = _post_fork_details(slot=100)
        cc = Mock(
            get_block_details=Mock(return_value=details),
            get_state_latest_block_hash=Mock(return_value=BlockHash("0xownhash")),
        )

        # Act
        bs = BlockstampBuilder(cc, el).get_blockstamp_by_state('head')

        # Assert
        cc.get_block_root.assert_called_once_with('head')
        assert bs.block_hash == add_0x_prefix("0xownhash")


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
        # Arrange: the block is at (or after) the last finalized slot, so it has no finalized child.
        cc = Mock()

        # Act / Assert
        with pytest.raises(ChildSlotNotFinalized):
            get_next_non_missed_slot(cc, SlotNumber(200), last_finalized_slot_number=SlotNumber(200))
