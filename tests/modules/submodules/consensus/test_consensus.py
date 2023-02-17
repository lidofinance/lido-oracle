from http import HTTPStatus
from unittest.mock import Mock
import pytest

from src.modules.submodules.consensus import (
    MemberInfo, ZERO_HASH, IsNotMemberException,
    NoSlotsAvailable,
)
from src.providers.http_provider import NotOkResponse
from src.typings import BlockStamp, RefBlockStamp
from tests.modules.submodules.consensus.conftest import get_blockstamp_by_state


@pytest.mark.unit
def test_get_latest_blockstamp(consensus):
    bs = consensus._get_latest_blockstamp()
    assert isinstance(bs, BlockStamp)


# ------ MemberInfo tests ---------

@pytest.mark.unit
def test_get_member_info_with_account(consensus, set_report_account):
    bs = consensus._get_latest_blockstamp()
    member_info = consensus._get_member_info(bs)

    assert isinstance(member_info, MemberInfo)

    assert member_info.is_report_member
    assert not member_info.is_submit_member
    assert member_info.is_fast_lane
    assert member_info.current_frame_consensus_report != ZERO_HASH


@pytest.mark.unit
def test_get_member_info_without_account(consensus, set_no_account):
    bs = consensus._get_latest_blockstamp()
    member_info = consensus._get_member_info(bs)

    assert isinstance(member_info, MemberInfo)

    assert member_info.is_report_member
    assert member_info.is_submit_member
    assert member_info.is_fast_lane
    assert member_info.current_frame_consensus_report == ZERO_HASH


@pytest.mark.unit
def test_get_member_info_no_member_account(consensus, set_not_member_account):
    bs = consensus._get_latest_blockstamp()

    with pytest.raises(IsNotMemberException):
        consensus._get_member_info(bs)


@pytest.mark.unit
def test_get_member_info_submit_only_account(consensus, set_submit_account):
    bs = consensus._get_latest_blockstamp()
    member_info = consensus._get_member_info(bs)

    assert isinstance(member_info, MemberInfo)

    assert not member_info.is_report_member
    assert member_info.is_submit_member
    assert not member_info.is_fast_lane


# ------ Get block for report tests ----------

@pytest.mark.unit
@pytest.mark.possible_integration
def test_get_blockstamp_for_report_slot_not_finalized(web3, consensus, caplog):
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')
    current_frame = consensus._get_current_frame(latest_blockstamp)
    previous_blockstamp = get_blockstamp_by_state(web3, current_frame.ref_slot - 1)
    consensus._get_latest_blockstamp = Mock(return_value=previous_blockstamp)

    consensus.get_blockstamp_for_report(latest_blockstamp)
    assert "Reference slot is not yet finalized" in caplog.messages[-1]


@pytest.mark.unit
@pytest.mark.possible_integration
def test_get_blockstamp_for_report_slot_deadline_missed(web3, consensus, caplog):
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')
    member_info = consensus._get_member_info(latest_blockstamp)
    member_info.deadline_slot = latest_blockstamp.slot_number - 1
    consensus._get_member_info = Mock(return_value=member_info)

    consensus.get_blockstamp_for_report(latest_blockstamp)
    assert "Deadline missed" in caplog.messages[-1]


@pytest.mark.unit
@pytest.mark.possible_integration
def test_get_blockstamp_for_report_slot_member_is_not_in_fast_line_not_ready(web3, consensus, caplog):
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')
    member_info = consensus._get_member_info(latest_blockstamp)
    member_info.is_fast_lane = False
    member_info.current_frame_ref_slot = latest_blockstamp.slot_number - 1
    consensus._get_member_info = Mock(return_value=member_info)

    consensus.get_blockstamp_for_report(latest_blockstamp)
    assert "report will be postponed" in caplog.messages[-1]


@pytest.mark.unit
@pytest.mark.possible_integration
def test_get_blockstamp_for_report_slot_member_is_not_in_fast_line_ready(web3, consensus, caplog):
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')
    member_info = consensus._get_member_info(latest_blockstamp)
    member_info.is_fast_lane = False
    member_info.current_frame_ref_slot += 1
    consensus._get_member_info = Mock(return_value=member_info)

    blockstamp, ref_slot = consensus.get_blockstamp_for_report(latest_blockstamp)
    assert isinstance(blockstamp, BlockStamp)


@pytest.mark.unit
@pytest.mark.possible_integration
def test_get_blockstamp_for_report_slot_member_ready_to_report(web3, consensus, caplog):
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')
    blockstamp, ref_slot = consensus.get_blockstamp_for_report(latest_blockstamp)
    assert isinstance(blockstamp, BlockStamp)


# ------ Get first non missed slot ------------
@pytest.mark.unit
@pytest.mark.possible_integration
def test_get_first_non_missed_slot(web3, consensus):
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')
    frame_config = consensus._get_frame_config(latest_blockstamp)
    chain_config = consensus._get_chain_config(latest_blockstamp)

    blockstamp = consensus._get_first_non_missed_slot(latest_blockstamp, latest_blockstamp.slot_number)
    assert isinstance(blockstamp, RefBlockStamp)
    left_border = latest_blockstamp.slot_number - frame_config.epochs_per_frame * chain_config.slots_per_epoch
    right_border = latest_blockstamp.slot_number
    assert left_border < blockstamp.slot_number <= right_border


@pytest.mark.unit
@pytest.mark.possible_integration
def test_get_third_non_missed_slot(web3, consensus):
    def get_block_root(_):
        setattr(get_block_root, "call_count", getattr(get_block_root, "call_count", 0) + 1)
        if getattr(get_block_root, "call_count") == 3:
            web3.cc.get_block_root = original
        raise NotOkResponse("No slots", status=HTTPStatus.NOT_FOUND, text="text")

    latest_blockstamp = get_blockstamp_by_state(web3, 'head')

    original = web3.cc.get_block_root
    web3.cc.get_block_root = Mock(side_effect=get_block_root)
    blockstamp = consensus._get_first_non_missed_slot(latest_blockstamp, latest_blockstamp.slot_number)
    assert isinstance(blockstamp, RefBlockStamp)
    assert blockstamp.slot_number < latest_blockstamp.slot_number


@pytest.mark.unit
@pytest.mark.possible_integration
def test_all_slots_are_missed(web3, consensus):
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')
    web3.cc.get_block_root = Mock(side_effect=NotOkResponse("No slots", status=HTTPStatus.NOT_FOUND, text="text"))
    with pytest.raises(NoSlotsAvailable):
        consensus._get_first_non_missed_slot(latest_blockstamp, latest_blockstamp.slot_number)
