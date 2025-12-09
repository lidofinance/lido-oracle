from typing import cast
from dataclasses import dataclass
from unittest.mock import Mock

import pytest
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from web3.exceptions import ContractCustomError

from src import variables
from src.modules.submodules import consensus as consensus_module
from src.modules.submodules.consensus import ZERO_HASH, ConsensusModule, IsNotMemberException, MemberInfo
from src.modules.submodules.exceptions import IncompatibleOracleVersion, ContractVersionMismatch
from src.modules.submodules.types import ChainConfig
from src.providers.consensus.types import BeaconSpecResponse
from src.types import BlockStamp, ReferenceBlockStamp

from tests.factory.blockstamp import ReferenceBlockStampFactory, BlockStampFactory
from tests.factory.configs import (
    BeaconSpecResponseFactory,
    ChainConfigFactory,
    FrameConfigFactory,
    BlockDetailsResponseFactory,
)
from tests.factory.member_info import MemberInfoFactory


@dataclass
class Account:
    address: ChecksumAddress
    _private_key: HexBytes


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
def test_get_latest_blockstamp(consensus, set_no_account):
    consensus.w3.cc.get_state_block_roots.return_value = "0x0000000000000000000000000000000000000000"
    consensus.w3.cc.get_block_details.return_value = BlockDetailsResponseFactory.build()

    bs = consensus._get_latest_blockstamp()

    assert isinstance(bs, BlockStamp)


# ------ MemberInfo tests ---------
@pytest.mark.unit
def test_get_member_info_with_account(consensus, set_report_account):
    bs = ReferenceBlockStampFactory.build()
    consensus.w3.eth.get_balance = Mock(return_value=1)
    consensus._get_consensus_contract(bs).get_consensus_state_for_member.return_value = (
        0,  # current_frame_ref_slot
        0,  # current_frame_consensus_report
        True,  # is_member
        True,  # is_fast_lane
        True,  # can_report
        0,  # last_member_report_ref_slot
        0,  # current_frame_member_report
    )
    consensus.report_contract.has_role.return_value = False

    member_info = consensus.get_member_info(bs)

    assert isinstance(member_info, MemberInfo)
    assert member_info.is_report_member
    assert not member_info.is_submit_member
    assert member_info.is_fast_lane
    assert member_info.current_frame_consensus_report != ZERO_HASH


@pytest.mark.unit
def test_get_member_info_without_account(consensus, set_no_account):
    bs = ReferenceBlockStampFactory.build()
    consensus.w3.eth.get_balance = Mock(return_value=1)
    member_info = consensus.get_member_info(bs)

    assert isinstance(member_info, MemberInfo)

    assert member_info.is_report_member
    assert member_info.is_submit_member
    assert member_info.is_fast_lane
    assert member_info.current_frame_consensus_report == ZERO_HASH


@pytest.mark.unit
def test_get_member_info_no_member_account(consensus, set_not_member_account):
    bs = ReferenceBlockStampFactory.build()
    consensus.w3.eth.get_balance = Mock(return_value=1)
    consensus._get_consensus_contract(bs).get_consensus_state_for_member.return_value = (
        0,  # current_frame_ref_slot
        0,  # current_frame_consensus_report
        False,  # is_member
        True,  # is_fast_lane
        True,  # can_report
        0,  # last_member_report_ref_slot
        0,  # current_frame_member_report
    )
    consensus.report_contract.has_role.return_value = False

    with pytest.raises(IsNotMemberException):
        consensus.get_member_info(bs)


@pytest.mark.unit
def test_get_member_info_submit_only_account(consensus, set_submit_account):
    bs = ReferenceBlockStampFactory.build()
    consensus.w3.eth.get_balance = Mock(return_value=1)
    consensus._get_consensus_contract(bs).get_consensus_state_for_member.return_value = (
        0,  # current_frame_ref_slot
        0,  # current_frame_consensus_report
        False,  # is_member
        False,  # is_fast_lane
        True,  # can_report
        0,  # last_member_report_ref_slot
        0,  # current_frame_member_report
    )
    consensus.report_contract.has_role.return_value = True

    member_info = consensus.get_member_info(bs)

    assert isinstance(member_info, MemberInfo)
    assert not member_info.is_report_member
    assert member_info.is_submit_member
    assert not member_info.is_fast_lane


@pytest.mark.unit
def test_get_blockstamp_for_report_slot_not_finalized(web3, consensus, caplog, set_no_account):
    blockstamp = ReferenceBlockStampFactory.build(slot_number=1)
    member_info = MemberInfoFactory.build(is_report_member=True, current_frame_ref_slot=2)
    consensus.get_member_info = Mock(return_value=member_info)
    consensus._get_latest_blockstamp = Mock(return_value=blockstamp)

    consensus.get_blockstamp_for_report(blockstamp)

    assert "Reference slot is not yet finalized" in caplog.messages[-1]


@pytest.mark.unit
def test_get_frame_custom_exception(web3, consensus):
    bs = ReferenceBlockStampFactory.build()

    consensus_contract = Mock(get_current_frame=Mock(side_effect=ContractCustomError('0x12345678', '0x12345678')))
    consensus._get_consensus_contract = Mock(return_value=consensus_contract)

    with pytest.raises(ContractCustomError):
        consensus.get_initial_or_current_frame(bs)


@pytest.fixture()
def use_account(request):
    if request.param:
        request.getfixturevalue("set_submit_account")
    else:
        request.getfixturevalue("set_no_account")


@pytest.mark.unit
@pytest.mark.parametrize(
    "use_account", [True, False], ids=['with_account', "without_account"], indirect=["use_account"]
)
def test_first_frame_is_not_yet_started(web3, consensus, caplog, use_account):
    bs = ReferenceBlockStampFactory.build()
    err = ContractCustomError('0xcd0883ea', '0xcd0883ea')
    consensus_contract = Mock(
        get_current_frame=Mock(side_effect=err), get_consensus_state_for_member=Mock(side_effect=err)
    )
    consensus._get_consensus_contract = Mock(return_value=consensus_contract)
    consensus.report_contract.submit_data_role = Mock(return_value='0x0')
    consensus.report_contract.has_role = Mock(return_value=True)
    consensus.get_frame_config = Mock(return_value=FrameConfigFactory.build(initial_epoch=5, epochs_per_frame=10))
    consensus.get_chain_config = Mock(return_value=ChainConfigFactory.build())

    first_frame = consensus.get_initial_or_current_frame(bs)
    consensus.w3.eth.get_balance = Mock(return_value=1)
    member_info = consensus.get_member_info(bs)

    assert first_frame.ref_slot == 5 * 32 - 1
    assert first_frame.report_processing_deadline_slot == (5 + 10) * 32 - 1
    assert member_info.is_submit_member
    assert member_info.is_report_member
    assert member_info.is_fast_lane
    assert member_info.current_frame_consensus_report == ZERO_HASH
    assert member_info.current_frame_member_report == ZERO_HASH
    assert member_info.current_frame_ref_slot == first_frame.ref_slot
    assert member_info.deadline_slot == first_frame.report_processing_deadline_slot


@pytest.mark.unit
def test_get_blockstamp_for_report_slot_deadline_missed(web3, consensus, caplog, set_no_account):
    blockstamp = ReferenceBlockStampFactory.build(slot_number=2)
    member_info = MemberInfoFactory.build(is_report_member=True, current_frame_ref_slot=1, deadline_slot=1)
    consensus.get_member_info = Mock(return_value=member_info)
    consensus._get_latest_blockstamp = Mock(return_value=blockstamp)

    consensus.get_blockstamp_for_report(blockstamp)

    assert "Deadline missed" in caplog.messages[-1]


@pytest.mark.unit
@pytest.mark.parametrize(
    'contract_version,consensus_version',
    [
        # pytest.param(1, 2, marks=pytest.mark.xfail(raises=IncompatibleOracleVersion, strict=True)),
        pytest.param(3, 3, marks=pytest.mark.xfail(raises=IncompatibleOracleVersion, strict=True)),
        (2, 2),
    ],
)
def test_incompatible_oracle(consensus, contract_version, consensus_version):
    bs = ReferenceBlockStampFactory.build()

    consensus.report_contract.get_contract_version = Mock(return_value=contract_version)
    consensus.report_contract.get_consensus_version = Mock(return_value=consensus_version)

    consensus._check_compatability(bs)


@pytest.mark.unit
@pytest.mark.parametrize(
    'contract_version,consensus_version,expected',
    [
        pytest.param(3, 3, False, marks=pytest.mark.xfail(raises=ContractVersionMismatch, strict=True)),
        pytest.param(4, 4, False, marks=pytest.mark.xfail(raises=ContractVersionMismatch, strict=True)),
        pytest.param(2, 2, False, marks=pytest.mark.xfail(raises=ContractVersionMismatch, strict=True)),
        (3, 2, True),
    ],
)
def test_contract_upgrade_before_report_submited(consensus, contract_version, consensus_version, expected):
    bs = ReferenceBlockStampFactory.build()

    check_latest_contract = lambda tag: contract_version if tag == 'latest' else 3
    consensus.report_contract.get_contract_version = Mock(side_effect=check_latest_contract)

    check_latest_consensus = lambda tag: consensus_version if tag == 'latest' else 2
    consensus.report_contract.get_consensus_version = Mock(side_effect=check_latest_consensus)

    assert expected == consensus._check_compatability(bs)


@pytest.mark.unit
def test_incompatible_contract_version(consensus):
    bs = ReferenceBlockStampFactory.build()

    consensus.report_contract.get_contract_version = Mock(return_value=3)
    consensus.report_contract.get_consensus_version = Mock(return_value=3)

    with pytest.raises(IncompatibleOracleVersion):
        consensus._check_compatability(bs)


@pytest.mark.unit
def test_get_blockstamp_for_report_contract_is_not_reportable(consensus: ConsensusModule, caplog):
    bs = ReferenceBlockStampFactory.build()
    consensus._get_latest_blockstamp = Mock(return_value=bs)
    consensus._check_contract_versions = Mock(return_value=True)
    consensus.is_contract_reportable = Mock(return_value=False)

    consensus.get_blockstamp_for_report(bs)
    assert "Contract is not reportable" in caplog.messages[-1]


@pytest.mark.unit
def test_get_blockstamp_for_report_slot_member_is_not_in_fast_line_ready(web3, consensus, caplog, set_no_account):
    blockstamp = ReferenceBlockStampFactory.build(slot_number=2)
    member_info = MemberInfoFactory.build(
        is_report_member=True,
        is_fast_lane=False,
        current_frame_ref_slot=1,
    )
    consensus.get_member_info = Mock(return_value=member_info)
    consensus._get_latest_blockstamp = Mock(return_value=blockstamp)
    consensus._get_consensus_contract(blockstamp).get_chain_config.return_value = ChainConfigFactory.build()
    consensus.w3.cc.get_block_details.return_value = BlockDetailsResponseFactory.build()

    blockstamp = consensus.get_blockstamp_for_report(blockstamp)
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


@pytest.mark.unit
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


@pytest.mark.unit
def test_get_web3_converter(consensus):
    blockstamp = BlockStampFactory.build()

    fc = FrameConfigFactory.build()
    cc = ChainConfigFactory.build()

    consensus.get_frame_config = Mock(return_value=fc)
    consensus.get_chain_config = Mock(return_value=cc)

    converter = consensus._get_web3_converter(blockstamp)

    consensus.get_frame_config.assert_called_once_with(blockstamp)
    consensus.get_chain_config.assert_called_once_with(blockstamp)

    assert converter.frame_config == fc
    assert converter.chain_config == cc


@pytest.mark.unit
def test_get_frame_number_by_slot__known_slot_and_config__returns_expected_frame_number(consensus):
    blockstamp = ReferenceBlockStampFactory.build(ref_slot=1000000)

    chain_config = ChainConfigFactory.build(
        slots_per_epoch=32,
        genesis_time=1606824023,
    )
    frame_config = FrameConfigFactory.build(
        initial_epoch=0,
        epochs_per_frame=225,
    )

    consensus.get_chain_config = Mock(return_value=chain_config)
    consensus.get_frame_config = Mock(return_value=frame_config)

    result = consensus.get_frame_number_by_slot(blockstamp)

    expected_frame = 138
    assert result == expected_frame
