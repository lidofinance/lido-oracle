from unittest.mock import Mock

import pytest
from hexbytes import HexBytes
from src import variables
from src.modules.accounting.types import ReportData
from src.modules.submodules.types import ChainConfig, FrameConfig, ZERO_HASH
from tests.conftest import Account

from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.member_info import MemberInfoFactory


@pytest.fixture()
def set_report_account(monkeypatch):
    with monkeypatch.context():
        monkeypatch.setattr(
            variables,
            "ACCOUNT",
            Account(
                address='0xF6d4bA61810778fF95BeA0B7DB2F103Dc042C5f7',
                _private_key='0x0',
            ),
        )
        yield


@pytest.fixture
def mock_latest_data(consensus):
    blockstamp = ReferenceBlockStampFactory.build()
    consensus._get_latest_blockstamp = Mock(return_value=blockstamp)
    member_info = MemberInfoFactory.build(current_frame_consensus_report=int.to_bytes(1, 32))
    consensus.get_member_info = Mock(return_value=member_info)


# ----- Process report main ----------
@pytest.mark.unit
def test_process_report_main(consensus, tx_utils, caplog):
    consensus.w3.lido_contracts.accounting_oracle.get_consensus_version = Mock(return_value=1)
    consensus.w3.lido_contracts.accounting_oracle.get_contract_version = Mock(return_value=1)
    blockstamp = ReferenceBlockStampFactory.build()
    consensus._get_latest_blockstamp = Mock(return_value=blockstamp)
    member_info = MemberInfoFactory.build(is_report_member=True, current_frame_consensus_report=ZERO_HASH)
    consensus.get_member_info = Mock(return_value=member_info)
    consensus._send_report_hash = Mock()
    report_data = ReportData(
        1, 2, 3, 4, [5, 6], [7, 8], 9, 10, 11, [12], 13, True, 13, HexBytes(int.to_bytes(14, 32)), 15
    ).as_tuple()
    consensus.build_report = Mock(return_value=report_data)

    consensus.process_report(blockstamp)
    assert "Build report." in caplog.text
    assert "Calculate report hash." in caplog.text
    assert "Send report hash" in caplog.text
    assert "Quorum is not ready" in caplog.text


# ----- Hash calculations ----------
@pytest.mark.unit
def test_hash_calculations(consensus):
    rd = ReportData(1, 2, 3, 4, [5, 6], [7, 8], 9, 10, 11, [12], 13, True, 13, HexBytes(int.to_bytes(14, 32)), 15)
    report_hash = consensus._encode_data_hash(rd.as_tuple())
    assert isinstance(report_hash, HexBytes)
    assert report_hash == HexBytes('0x8028b6539e5a5690c15e14f075bd6484fbaa4a6dc2e39e9d1fe9000a5dfa9d14')


# ------ Process report hash -----------
@pytest.mark.unit
def test_report_hash(web3, consensus, tx_utils, set_report_account):
    consensus.w3.lido_contracts.accounting_oracle.get_consensus_version = Mock(return_value=1)
    blockstamp = ReferenceBlockStampFactory.build()
    consensus._get_latest_blockstamp = Mock(return_value=blockstamp)
    member_info = MemberInfoFactory.build(is_report_member=True)
    consensus.get_member_info = Mock(return_value=member_info)
    consensus._send_report_hash = Mock()
    consensus._process_report_hash(blockstamp, HexBytes(int.to_bytes(1, 32)))
    consensus._send_report_hash.assert_called_once()


@pytest.mark.unit
def test_report_hash_member_not_in_fast_lane(web3, consensus, caplog):
    blockstamp = ReferenceBlockStampFactory.build()
    consensus._get_latest_blockstamp = Mock(return_value=blockstamp)
    member_info = MemberInfoFactory.build(
        is_fast_lane=False,
        current_frame_ref_slot=blockstamp.slot_number - 1,
        is_report_member=True,
    )
    consensus.get_member_info = Mock(return_value=member_info)

    consensus._process_report_hash(blockstamp, HexBytes(int.to_bytes(1, 32)))
    assert "report will be postponed" in caplog.messages[-1]


@pytest.mark.unit
def test_report_hash_member_is_not_report_member(consensus, caplog):
    blockstamp = ReferenceBlockStampFactory.build()
    consensus._get_latest_blockstamp = Mock(return_value=blockstamp)
    member_info = MemberInfoFactory.build(
        is_report_member=False,
    )
    consensus.get_member_info = Mock(return_value=member_info)

    consensus._process_report_hash(blockstamp, HexBytes(int.to_bytes(1, 32)))
    assert "Account can`t submit report hash" in caplog.messages[-1]


@pytest.mark.unit
def test_do_not_report_same_hash(consensus, caplog, mock_latest_data):
    blockstamp = ReferenceBlockStampFactory.build()
    consensus._get_latest_blockstamp = Mock(return_value=blockstamp)
    member_info = MemberInfoFactory.build(
        is_report_member=True,
        current_frame_member_report=int.to_bytes(1, 32),
    )
    consensus.get_member_info = Mock(return_value=member_info)

    consensus._process_report_hash(blockstamp, HexBytes(int.to_bytes(1, 32)))
    assert "Account already submitted provided hash." in caplog.messages[-1]


# -------- Process report data ---------
@pytest.mark.unit
def test_quorum_is_no_ready(consensus, caplog):
    blockstamp = ReferenceBlockStampFactory.build()
    consensus._get_latest_blockstamp = Mock(return_value=blockstamp)
    member_info = MemberInfoFactory.build(current_frame_consensus_report=ZERO_HASH)
    consensus.get_member_info = Mock(return_value=member_info)

    report_data = tuple()
    report_hash = int.to_bytes(1, 32)
    consensus._process_report_data(blockstamp, report_data, report_hash)
    assert "Quorum is not ready." in caplog.messages[-1]


@pytest.mark.unit
def test_process_report_data_hash_differs_from_quorums(consensus, caplog, mock_latest_data):
    blockstamp = ReferenceBlockStampFactory.build()
    report_data = tuple()
    report_hash = int.to_bytes(2, 32)

    consensus._process_report_data(blockstamp, report_data, report_hash)
    assert "Oracle`s hash differs from consensus report hash." in caplog.messages[-1]


@pytest.mark.unit
def test_process_report_data_already_submitted(consensus, caplog, mock_latest_data):
    blockstamp = ReferenceBlockStampFactory.build()
    report_data = tuple()
    report_hash = int.to_bytes(1, 32)

    consensus._process_report_data(blockstamp, report_data, report_hash)
    assert "Main data already submitted." in caplog.messages[-1]


@pytest.mark.unit
def test_process_report_data_main_data_submitted(consensus, caplog, mock_latest_data):
    blockstamp = ReferenceBlockStampFactory.build()
    report_data = tuple()
    report_hash = int.to_bytes(1, 32)
    consensus._get_slot_delay_before_data_submit = Mock(return_value=0)

    consensus.is_main_data_submitted = Mock(side_effect=[False, True])

    consensus._process_report_data(blockstamp, report_data, report_hash)
    assert "Main data already submitted." in caplog.messages[-1]
    assert "Sleep for" not in caplog.text


@pytest.mark.unit
def test_process_report_data_main_sleep_until_data_submitted(consensus, caplog, tx_utils, mock_latest_data):
    consensus.w3.lido_contracts.accounting_oracle.get_consensus_version = Mock(return_value=1)
    consensus.w3.lido_contracts.accounting_oracle.get_contract_version = Mock(return_value=1)
    consensus.get_chain_config = Mock(
        return_value=ChainConfig(
            slots_per_epoch=32,
            seconds_per_slot=0,
            genesis_time=0,
        )
    )
    blockstamp = ReferenceBlockStampFactory.build()
    report_data = ReportData(
        1, 2, 3, 4, [5, 6], [7, 8], 9, 10, 11, [12], 13, True, 13, HexBytes(int.to_bytes(14, 32)), 15
    ).as_tuple()
    report_hash = int.to_bytes(1, 32)

    consensus.is_main_data_submitted = Mock(return_value=False)
    consensus._get_slot_delay_before_data_submit = Mock(return_value=100)
    consensus._submit_report = Mock()

    consensus._process_report_data(blockstamp, report_data, report_hash)
    assert "Sleep for 100 slots before sending data." in caplog.text
    assert "Send report data. Contract version: [1]" in caplog.text


@pytest.mark.unit
def test_process_report_data_sleep_ends(consensus, caplog, mock_latest_data):
    consensus.get_chain_config = Mock(
        return_value=ChainConfig(
            slots_per_epoch=32,
            seconds_per_slot=0,
            genesis_time=0,
        )
    )
    blockstamp = ReferenceBlockStampFactory.build()
    report_data = tuple()
    report_hash = int.to_bytes(1, 32)

    false_count = 9999
    main_data_submitted_n_times = [False] * false_count + [True]
    consensus.is_main_data_submitted = Mock(side_effect=main_data_submitted_n_times)
    consensus._get_slot_delay_before_data_submit = Mock(return_value=10000)

    consensus._process_report_data(blockstamp, report_data, report_hash)
    assert "Sleep for 10000 slots before sending data." in caplog.text
    assert "Main data already submitted." in caplog.text


@pytest.mark.unit
def test_process_report_submit_report(consensus, tx_utils, caplog, mock_latest_data):
    consensus.w3.lido_contracts.accounting_oracle.get_consensus_version = Mock(return_value=1)
    consensus.w3.lido_contracts.accounting_oracle.get_contract_version = Mock(return_value=1)
    blockstamp = ReferenceBlockStampFactory.build()
    report_data = ReportData(
        1, 2, 3, 4, [5, 6], [7, 8], 9, 10, 11, [12], 13, True, 13, HexBytes(int.to_bytes(14, 32)), 15
    ).as_tuple()
    report_hash = int.to_bytes(1, 32)

    main_data_submitted_base = [False, False]
    consensus.is_main_data_submitted = Mock(side_effect=main_data_submitted_base)
    consensus._get_slot_delay_before_data_submit = Mock(return_value=0)

    consensus._submit_report = Mock()

    consensus._process_report_data(blockstamp, report_data, report_hash)
    assert "Send report data. Contract version: [1]" in caplog.text


# ----- Test sleep calculations
@pytest.fixture
def mock_configs(consensus):
    consensus.get_chain_config = Mock(
        return_value=ChainConfig(
            slots_per_epoch=32,
            seconds_per_slot=0,
            genesis_time=0,
        )
    )
    consensus.get_frame_config = Mock(
        return_value=FrameConfig(
            initial_epoch=0,
            epochs_per_frame=12,
            fast_lane_length_slots=10,
        )
    )
    consensus.get_member_info = Mock(return_value=MemberInfoFactory.build(is_submit_member=False))


@pytest.mark.unit
def test_get_slot_delay_before_data_submit(consensus, caplog, set_report_account, mock_configs):
    consensus._get_consensus_contract_members = Mock(return_value=([variables.ACCOUNT.address], None))
    delay = consensus._get_slot_delay_before_data_submit(ReferenceBlockStampFactory.build())
    assert delay == variables.SUBMIT_DATA_DELAY_IN_SLOTS
    assert "Calculate slots delay." in caplog.messages[-1]


@pytest.mark.unit
def test_get_slot_delay_before_data_submit_three_members(consensus, caplog, set_report_account, mock_configs):
    blockstamp = ReferenceBlockStampFactory.build()
    consensus._get_consensus_contract_members = Mock(return_value=[[variables.ACCOUNT.address, '0x1', '0x2'], None])
    delay = consensus._get_slot_delay_before_data_submit(blockstamp)
    assert delay == variables.SUBMIT_DATA_DELAY_IN_SLOTS * 3
    assert "Calculate slots delay." in caplog.messages[-1]
