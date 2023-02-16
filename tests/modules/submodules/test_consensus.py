from http import HTTPStatus
from unittest.mock import Mock
import pytest

from src.modules.submodules.consensus import (
    ConsensusModule, MemberInfo, ZERO_HASH, IsNotMemberException,
    NoSlotsAvailable,
)
from src.providers.http_provider import NotOkResponse
from src.typings import BlockStamp, SlotNumber, BlockNumber


class SimpleConsensusModule(ConsensusModule):
    CONSENSUS_VERSION = 1
    CONTRACT_VERSION = 1

    def __init__(self, w3):
        self.report_contract = w3.lido_contracts.accounting_oracle
        super().__init__(w3)

    def build_report(self, blockstamp: BlockStamp, ref_slot: SlotNumber) -> tuple:
        return tuple()

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        return True

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        return True


@pytest.fixture()
def consensus(web3, consensus_client, contracts):
    return SimpleConsensusModule(web3)


def get_blockstamp_by_state(w3, state_id) -> BlockStamp:
    root = w3.cc.get_block_root(state_id).root
    slot_details = w3.cc.get_block_details(root)

    return BlockStamp(
        block_root=root,
        slot_number=SlotNumber(int(slot_details.message.slot)),
        state_root=slot_details.message.state_root,
        block_number=BlockNumber(int(slot_details.message.body['execution_payload']['block_number'])),
        block_hash=slot_details.message.body['execution_payload']['block_hash']
    )


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
    assert isinstance(blockstamp, BlockStamp)
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
    assert isinstance(blockstamp, BlockStamp)
    assert blockstamp.slot_number < latest_blockstamp.slot_number


@pytest.mark.unit
@pytest.mark.possible_integration
def test_all_slots_are_missed(web3, consensus):
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')
    web3.cc.get_block_root = Mock(side_effect=NotOkResponse("No slots", status=HTTPStatus.NOT_FOUND, text="text"))
    with pytest.raises(NoSlotsAvailable):
        consensus._get_first_non_missed_slot(latest_blockstamp, latest_blockstamp.slot_number)


# ----- Hash calculations ----------
def test_hash_calculations(consensus):
    pass


# ------ Process report hash -----------
def test_report_hash(consensus):
    pass


def test_do_not_report_same_hash(consensus):
    pass


# -------- Process report data ---------
def test_process_report_data_hash_differs(consensus):
    pass


def test_process_report_data_wait_for_consensus(consensus):
    pass


def test_process_report_data_hash_differs_from_quorums(consensus):
    pass


def test_process_report_data_main_data_submitted(consensus):
    # Check there is no sleep
    pass


def test_process_report_data_main_sleep_until_data_submitted(consensus):
    # It should wake in half of the sleep
    pass


def test_process_report_data_sleep_ends(consensus):
    # No infinity sleep?
    pass


# ----- Test sleep calculations
def test_get_slot_delay_before_data_submit(consensus):
    pass
