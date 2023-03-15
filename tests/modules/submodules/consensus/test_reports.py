from unittest.mock import Mock

import pytest
from hexbytes import HexBytes
from src import variables
from src.modules.accounting.typings import Account
from src.modules.submodules.typings import ChainConfig

from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.conftest import get_blockstamp_by_state


@pytest.fixture()
def set_report_account(monkeypatch):
    with monkeypatch.context():
        monkeypatch.setattr(variables, "ACCOUNT", Account(
            address='0xF6d4bA61810778fF95BeA0B7DB2F103Dc042C5f7',
            _private_key='0x0',
        ))
        yield

# ----- Process report main ----------
def test_process_report_main(consensus, tx_utils, caplog):
    blockstamp = ReferenceBlockStampFactory.build()
    report_data = (1, 2, 3, 4, [5, 6], [7, 8], 9, 10, 11, 12, True, 13, HexBytes(int.to_bytes(14, 32)), 15)
    consensus.build_report = Mock(return_value=report_data)
    report = consensus.process_report(blockstamp)
    assert "Build report." and "Calculate report hash." in caplog.text

# ----- Hash calculations ----------
def test_hash_calculations(consensus):
    report_data = (1, 2, 3, 4, [5, 6], [7, 8], 9, 10, 11, 12, True, 13, HexBytes(int.to_bytes(14, 32)), 15)
    report_hash = consensus._get_report_hash(report_data)
    assert isinstance(report_hash, HexBytes)
    assert report_hash == b'\x10\xb7_&\xde\r\\\xbc\xc6a\xb5\xa1\x83u\xf6\x14\xf6:\xf9\r6:\x8cQ\xf6\xb2^\xffG\xee\xf5\xc1'


# ------ Process report hash -----------
def test_report_hash(web3, consensus, tx_utils, set_report_account):
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')
    consensus._process_report_hash(latest_blockstamp, HexBytes(int.to_bytes(1, 32)))
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


def test_process_report_data_hash_differs_from_quorums(web3, consensus, caplog):
    blockstamp = get_blockstamp_by_state(web3, 'head')
    member_info = consensus.get_member_info(blockstamp)
    member_info.current_frame_consensus_report = int.to_bytes(1, 32)
    consensus.get_member_info = Mock(return_value=member_info)
    report_data = tuple()
    report_hash = int.to_bytes(2, 32)

    consensus._process_report_data(blockstamp, report_data, report_hash)
    assert "Oracle`s hash differs from consensus report hash." in caplog.messages[-1]


def test_process_report_data_already_submitted(web3, consensus, caplog):
    blockstamp = get_blockstamp_by_state(web3, 'head')
    member_info = consensus.get_member_info(blockstamp)
    member_info.current_frame_consensus_report = int.to_bytes(1, 32)
    consensus.get_member_info = Mock(return_value=member_info)
    report_data = tuple()
    report_hash = int.to_bytes(1, 32)

    consensus._process_report_data(blockstamp, report_data, report_hash)
    assert "Main data already submitted." in caplog.messages[-1]


def test_process_report_data_main_data_submitted(web3, consensus, caplog):
    # Check there is no sleep
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')

    member_info = consensus.get_member_info(latest_blockstamp)
    member_info.current_frame_consensus_report = int.to_bytes(1, 32)
    consensus.get_member_info = Mock(return_value=member_info)

    report_data = tuple()
    report_hash = int.to_bytes(1, 32)

    consensus.is_main_data_submitted = Mock(side_effect = [False, True])

    report = consensus._process_report_data(latest_blockstamp, report_data, report_hash)
    assert "Sleep for" not in caplog.text


def test_process_report_data_main_sleep_until_data_submitted(consensus):
    # It should wake in half of the sleep
    #
    # Should it? There is nothing about it in consensus._process_report_data
    # Checking the same thing in test_process_report_data_sleep_ends
    pass


def test_process_report_data_sleep_ends(web3, consensus, caplog):
    # No infinity sleep?
    chain_configs = ChainConfig(
        slots_per_epoch=32,
        seconds_per_slot=0,
        genesis_time=0,
    )
    consensus.get_chain_config = Mock(return_value=chain_configs)
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')

    member_info = consensus.get_member_info(latest_blockstamp)
    member_info.current_frame_consensus_report = int.to_bytes(1, 32)
    consensus.get_member_info = Mock(return_value=member_info)

    report_data = tuple()
    report_hash = int.to_bytes(1, 32)

    # is_main_data_submitted False n times
    main_data_submitted_base = [False, True]
    main_data_submitted_false = 9999
    main_data_submitted_n_times = [main_data_submitted_base[0]]*main_data_submitted_false + [main_data_submitted_base[1]]
    consensus.is_main_data_submitted = Mock(side_effect = main_data_submitted_n_times)
    consensus._get_slot_delay_before_data_submit = Mock(return_value=10000)

    report = consensus._process_report_data(latest_blockstamp, report_data, report_hash)
    assert "Sleep for 10000 slots before sending data." in caplog.text
    assert "Main data was submitted." in caplog.messages[-1]


# ----- Test sleep calculations
def test_get_slot_delay_before_data_submit(consensus, caplog, set_report_account):
    blockstamp = ReferenceBlockStampFactory.build()
    delay = consensus._get_slot_delay_before_data_submit(blockstamp)
    assert "Calculate slots to sleep." and "6" in caplog.messages[-1]
    #TODO: sleep_count < 0
