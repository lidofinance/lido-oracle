from unittest.mock import Mock

import pytest
from hexbytes import HexBytes
from src import variables
from src.modules.accounting.typings import Account, ReportData

from tests.conftest import get_blockstamp_by_state
from tests.factory.blockstamp import ReferenceBlockStampFactory


@pytest.fixture()
def set_report_account(monkeypatch):
    with monkeypatch.context():
        monkeypatch.setattr(variables, "ACCOUNT", Account(
            address='0xF6d4bA61810778fF95BeA0B7DB2F103Dc042C5f7',
            _private_key='0x0',
        ))
        yield


# ----- Hash calculations ----------
def test_hash_calculations(consensus):
    rd = ReportData(1, 2, 3, 4, [5, 6], [7, 8], 9, 10, 11, [12], 13, True, 13, HexBytes(int.to_bytes(14, 32)), 15)
    report_hash = consensus._get_report_hash(rd.as_tuple())
    assert isinstance(report_hash, HexBytes)
    assert report_hash == HexBytes('0x8028b6539e5a5690c15e14f075bd6484fbaa4a6dc2e39e9d1fe9000a5dfa9d14')


# ------ Process report hash -----------
def test_report_hash(web3, consensus, tx_utils, set_report_account):
    bs = ReferenceBlockStampFactory.build()
    consensus._process_report_hash(bs, HexBytes(int.to_bytes(1, 32)))
    # TODO add check that report hash was submitted


def test_report_hash_member_not_in_fast_lane(web3, consensus, caplog):
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')
    member_info = consensus.get_member_info(latest_blockstamp)
    member_info.is_fast_lane = False
    member_info.current_frame_ref_slot = latest_blockstamp.slot_number - 1
    consensus.get_member_info = Mock(return_value=member_info)

    consensus._process_report_hash(latest_blockstamp, HexBytes(int.to_bytes(1, 32)))
    assert "report will be postponed" in caplog.messages[-1]


def test_report_hash_member_is_not_report_member(web3, consensus, caplog):
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')
    member_info = consensus.get_member_info(latest_blockstamp)
    member_info.is_report_member = False
    consensus.get_member_info = Mock(return_value=member_info)

    consensus._process_report_hash(latest_blockstamp, HexBytes(int.to_bytes(1, 32)))
    assert "Account can`t submit report hash" in caplog.messages[-1]


def test_do_not_report_same_hash(web3, consensus, caplog):
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')
    member_info = consensus.get_member_info(latest_blockstamp)

    consensus._process_report_hash(latest_blockstamp, HexBytes(member_info.current_frame_member_report))
    assert "Provided hash already submitted" in caplog.messages[-1]


# -------- Process report data ---------
def test_quorum_is_no_ready(web3, consensus, caplog):
    blockstamp = get_blockstamp_by_state(web3, "head")
    report_data = tuple()
    report_hash = int.to_bytes(1, 32)
    consensus._process_report_data(blockstamp, report_data, report_hash)
    assert "Quorum is not ready." in caplog.messages[-1]


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
