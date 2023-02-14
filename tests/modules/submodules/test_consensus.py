import pytest

from src import variables
from src.modules.submodules.consensus import ConsensusModule, MemberInfo, ZERO_HASH, IsNotMemberException
from src.typings import BlockStamp


class SimpleConsensusModule(ConsensusModule):
    CONSENSUS_VERSION = 1
    CONTRACT_VERSION = 1

    def __init__(self, w3):
        self.report_contract = w3.lido_contracts.accounting_oracle
        super().__init__(w3)

    def build_report(self, blockstamp: BlockStamp) -> tuple:
        return tuple()

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        return True

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        return True


@pytest.fixture()
def consensus(web3, consensus_client, contracts):
    return SimpleConsensusModule(web3)


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
    assert member_info.is_fast_line
    assert member_info.current_frame_consensus_report != ZERO_HASH


@pytest.mark.unit
def test_get_member_info_without_account(consensus):
    bs = consensus._get_latest_blockstamp()
    member_info = consensus._get_member_info(bs)

    assert isinstance(member_info, MemberInfo)

    assert member_info.is_report_member
    assert member_info.is_submit_member
    assert member_info.is_fast_line
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
    assert not member_info.is_fast_line


# ------ Get block for report tests ----------
def test_get_blockstamp_for_report_slot_not_finalized(consensus):
    pass


def test_get_blockstamp_for_report_slot_deadline_missed(consensus):
    pass


def test_get_blockstamp_for_report_slot_member_is_not_in_fast_line_not_ready(consensus):
    pass


def test_get_blockstamp_for_report_slot_member_is_not_in_fast_line_ready(consensus):
    pass


def test_get_blockstamp_for_report_slot_member_ready_to_report(consensus):
    pass


# ------ Get first non missed slot ------------
def test_get_first_non_missed_slot(consensus):
    pass


def test_get_third_non_missed_slot(consensus):
    pass


def test_all_slots_are_missed(consensus):
    pass


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
