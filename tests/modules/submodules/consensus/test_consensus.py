from typing import cast
from unittest.mock import Mock

import pytest

from src import variables
from src.modules.accounting.typings import Account
from src.modules.submodules import consensus as consensus_module
from src.modules.submodules.consensus import ZERO_HASH, ConsensusModule, IsNotMemberException, MemberInfo
from src.modules.submodules.typings import ChainConfig
from src.providers.consensus.typings import BeaconSpecResponse
from src.typings import BlockStamp, ReferenceBlockStamp
from tests.conftest import get_blockstamp_by_state
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import BeaconSpecResponseFactory, ChainConfigFactory
from tests.modules.submodules.consensus.conftest import consensus


@pytest.fixture()
def set_no_account(monkeypatch):
    with monkeypatch.context():
        monkeypatch.setattr(variables, "ACCOUNT", None)
        yield


@pytest.fixture()
def set_submit_account(monkeypatch):
    with monkeypatch.context():
        monkeypatch.setattr(
            variables,
            "ACCOUNT",
            Account(
                address='0xe576e37b0c3e52E45993D20161a6CB289e0c8CA1',
                _private_key='0x0',
            ),
        )
        yield


@pytest.fixture()
def set_not_member_account(monkeypatch):
    with monkeypatch.context():
        monkeypatch.setattr(
            variables,
            "ACCOUNT",
            Account(
                address='0x25F76608A3FbC9C75840E070e3c285ce1732F834',
                _private_key='0x0',
            ),
        )
        yield


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


@pytest.mark.unit
def test_get_latest_blockstamp(consensus):
    bs = consensus.get_latest_blockstamp()
    assert isinstance(bs, BlockStamp)


# ------ MemberInfo tests ---------
@pytest.mark.unit
def test_get_member_info_with_account(consensus, set_report_account):
    bs = ReferenceBlockStampFactory.build()
    member_info = consensus.get_member_info(bs)

    assert isinstance(member_info, MemberInfo)

    assert member_info.is_report_member
    assert not member_info.is_submit_member
    assert member_info.is_fast_lane
    assert member_info.current_frame_consensus_report != ZERO_HASH


@pytest.mark.unit
def test_get_member_info_without_account(consensus, set_no_account):
    bs = ReferenceBlockStampFactory.build()
    member_info = consensus.get_member_info(bs)

    assert isinstance(member_info, MemberInfo)

    assert member_info.is_report_member
    assert member_info.is_submit_member
    assert member_info.is_fast_lane
    assert member_info.current_frame_consensus_report == ZERO_HASH


@pytest.mark.unit
def test_get_member_info_no_member_account(consensus, set_not_member_account):
    bs = ReferenceBlockStampFactory.build()

    with pytest.raises(IsNotMemberException):
        consensus.get_member_info(bs)


@pytest.mark.unit
def test_get_member_info_submit_only_account(consensus, set_submit_account):
    bs = ReferenceBlockStampFactory.build()
    member_info = consensus.get_member_info(bs)

    assert isinstance(member_info, MemberInfo)

    assert not member_info.is_report_member
    assert member_info.is_submit_member
    assert not member_info.is_fast_lane


# ------ Get block for report tests ----------
@pytest.mark.unit
@pytest.mark.possible_integration
def test_get_blockstamp_for_report_slot_not_finalized(web3, consensus, caplog):
    bs = ReferenceBlockStampFactory.build()
    current_frame = consensus.get_current_frame(bs)
    previous_blockstamp = get_blockstamp_by_state(web3, current_frame.ref_slot - 1)
    consensus.get_latest_blockstamp = Mock(return_value=previous_blockstamp)

    consensus.get_blockstamp_for_report(previous_blockstamp)
    assert "Reference slot is not yet finalized" in caplog.messages[-1]


@pytest.mark.unit
@pytest.mark.possible_integration
def test_get_blockstamp_for_report_slot_deadline_missed(web3, consensus, caplog):
    bs = ReferenceBlockStampFactory.build()
    member_info = consensus.get_member_info(bs)
    member_info.deadline_slot = bs.slot_number - 1
    consensus.get_member_info = Mock(return_value=member_info)

    consensus.get_blockstamp_for_report(bs)
    assert "Deadline missed" in caplog.messages[-1]


@pytest.mark.unit
def test_get_blockstamp_for_report_version_mismatch(consensus: ConsensusModule, caplog):
    bs = ReferenceBlockStampFactory.build()
    consensus.get_latest_blockstamp = Mock(return_value=bs)
    consensus._check_contract_versions = Mock(return_value=False)

    consensus.get_blockstamp_for_report(bs)
    assert "Waiting for Contracts to be updated" in caplog.messages[-1]


@pytest.mark.unit
def test_get_blockstamp_for_report_contract_is_not_reportable(consensus: ConsensusModule, caplog):
    bs = ReferenceBlockStampFactory.build()
    consensus.get_latest_blockstamp = Mock(return_value=bs)
    consensus._check_contract_versions = Mock(return_value=True)
    consensus.is_contract_reportable = Mock(return_value=False)

    consensus.get_blockstamp_for_report(bs)
    assert "Contract is not reportable" in caplog.messages[-1]


@pytest.mark.unit
@pytest.mark.possible_integration
def test_get_blockstamp_for_report_slot_member_is_not_in_fast_line_ready(web3, consensus, caplog):
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')
    member_info = consensus.get_member_info(latest_blockstamp)
    member_info.is_fast_lane = False
    member_info.current_frame_ref_slot += 1
    consensus.get_member_info = Mock(return_value=member_info)

    blockstamp = consensus.get_blockstamp_for_report(latest_blockstamp)
    assert isinstance(blockstamp, BlockStamp)


@pytest.mark.unit
@pytest.mark.possible_integration
def test_get_blockstamp_for_report_slot_member_ready_to_report(web3, consensus, caplog):
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')
    blockstamp = consensus.get_blockstamp_for_report(latest_blockstamp)
    assert isinstance(blockstamp, BlockStamp)


class ConsensusImpl(ConsensusModule):
    """Consensus module implementation for testing purposes"""

    def build_report(self, _: ReferenceBlockStamp) -> tuple:
        return tuple()

    def is_main_data_submitted(self, _: BlockStamp) -> bool:
        return True

    def is_contract_reportable(self, _: BlockStamp) -> bool:
        return True

    def is_reporting_allowed(self, _: ReferenceBlockStamp) -> bool:
        return True


class NoReportContractConsensusImpl(ConsensusImpl):
    CONSENSUS_VERSION = 1
    CONTRACT_VERSION = 1


class NoConsensusVersionConsensusImpl(ConsensusImpl):
    report_contract = object()  # type: ignore
    CONTRACT_VERSION = 1


class NoContractVersionConsensusImpl(ConsensusImpl):
    report_contract = object()  # type: ignore
    CONSENSUS_VERSION = 1


@pytest.mark.parametrize(
    "impl",
    [
        NoReportContractConsensusImpl,
        NoConsensusVersionConsensusImpl,
        NoContractVersionConsensusImpl,
    ],
)
def test_no_report_contract(web3, impl: type[ConsensusModule]):
    with pytest.raises(NotImplementedError):
        impl(web3)


def test_check_contract_config(consensus: ConsensusModule, monkeypatch: pytest.MonkeyPatch):
    consensus.w3.cc.get_block_root = Mock(return_value=Mock(root=""))
    consensus.w3.cc.get_block_details = Mock()
    bs = ReferenceBlockStampFactory.build()
    with monkeypatch.context() as m:
        m.setattr(consensus_module, "build_blockstamp", Mock(return_value=bs))
        chain_config = cast(ChainConfig, ChainConfigFactory.build())
        consensus.get_chain_config = Mock(return_value=chain_config)
        bc_spec = cast(BeaconSpecResponse, BeaconSpecResponseFactory.build())
        consensus.w3.cc.get_config_spec = Mock(return_value=bc_spec)
        consensus.w3.cc.get_genesis = Mock(return_value=Mock(genesis_time=chain_config.genesis_time))

        consensus.check_contract_configs()

        # broken path
        chain_config = cast(
            ChainConfig,
            ChainConfigFactory.build(
                seconds_per_slot=14,
                slots_per_epoch=2,
                genesis_time=1,
            ),
        )
        consensus.get_chain_config = Mock(return_value=chain_config)
        with pytest.raises(ValueError):
            consensus.check_contract_configs()
