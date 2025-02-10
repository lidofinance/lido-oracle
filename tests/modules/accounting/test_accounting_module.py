from typing import Iterable, cast
from unittest.mock import Mock, patch

import pytest
from web3.exceptions import ContractCustomError
from web3.types import Wei

from src import variables
from src.constants import LIDO_DEPOSIT_AMOUNT
from src.modules.accounting import accounting as accounting_module
from src.modules.accounting.accounting import Accounting
from src.modules.accounting.accounting import logger as accounting_logger
from src.modules.accounting.third_phase.types import FormatList
from src.modules.accounting.types import LidoReportRebase, AccountingProcessingState
from src.modules.submodules.oracle_module import ModuleExecuteDelay
from src.modules.submodules.types import ChainConfig, FrameConfig, CurrentFrame, ZERO_HASH
from src.services.withdrawal import Withdrawal
from src.types import BlockStamp, ReferenceBlockStamp
from src.web3py.extensions.lido_validators import NodeOperatorId, StakingModule
from tests.factory.base_oracle import AccountingProcessingStateFactory
from tests.factory.blockstamp import BlockStampFactory, ReferenceBlockStampFactory
from tests.factory.configs import ChainConfigFactory, FrameConfigFactory
from tests.factory.contract_responses import LidoReportRebaseFactory
from tests.factory.no_registry import LidoValidatorFactory, StakingModuleFactory, PendingDepositFactory


@pytest.fixture(autouse=True)
def silence_logger() -> None:
    accounting_logger.disabled = True


@pytest.fixture
def accounting(web3, contracts):
    yield Accounting(web3)


@pytest.fixture
def bs() -> BlockStamp:
    return cast(BlockStamp, BlockStampFactory.build())


@pytest.fixture
def ref_bs() -> ReferenceBlockStamp:
    return cast(ReferenceBlockStamp, ReferenceBlockStampFactory.build())


@pytest.fixture
def chain_config() -> ChainConfig:
    return cast(ChainConfig, ChainConfigFactory.build())


@pytest.fixture
def frame_config() -> FrameConfig:
    return cast(FrameConfig, FrameConfigFactory.build())


@pytest.mark.unit
def test_accounting_execute_module(accounting: Accounting, bs: BlockStamp):
    accounting.get_blockstamp_for_report = Mock(return_value=None)
    assert (
        accounting.execute_module(last_finalized_blockstamp=bs) is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH
    ), "execute_module should wait for the next finalized epoch"
    accounting.get_blockstamp_for_report.assert_called_once_with(bs)

    accounting.get_blockstamp_for_report = Mock(return_value=bs)
    accounting.process_report = Mock(return_value=None)
    accounting.process_extra_data = Mock(return_value=None)
    assert (
        accounting.execute_module(last_finalized_blockstamp=bs) is ModuleExecuteDelay.NEXT_SLOT
    ), "execute_module should wait for the next slot"
    accounting.get_blockstamp_for_report.assert_called_once_with(bs)
    accounting.process_report.assert_called_once_with(bs)
    accounting.process_extra_data.assert_called_once_with(bs)


@pytest.mark.unit
def test_get_updated_modules_stats(accounting: Accounting):
    staking_modules: list[StakingModule] = [
        StakingModuleFactory.build(exited_validators_count=10),
        StakingModuleFactory.build(exited_validators_count=20),
        StakingModuleFactory.build(exited_validators_count=30),
    ]

    node_operators_stats = {
        (staking_modules[0].id, NodeOperatorId(0)): 10,
        (staking_modules[1].id, NodeOperatorId(0)): 25,
        (staking_modules[2].id, NodeOperatorId(0)): 30,
    }

    module_ids, exited_validators_count_list = accounting.get_updated_modules_stats(
        staking_modules,
        node_operators_stats,
    )

    assert len(module_ids) == 1
    assert module_ids[0] == staking_modules[1].id
    assert exited_validators_count_list[0] == 25


@pytest.mark.unit
@pytest.mark.usefixtures("lido_validators")
def test_get_consensus_lido_state(accounting: Accounting):
    bs = ReferenceBlockStampFactory.build()
    validators = [
        *[LidoValidatorFactory.build_transition_period_pending_deposit_vals() for _ in range(3)],
        *[LidoValidatorFactory.build_not_active_vals(bs.ref_epoch) for _ in range(3)],
        *[LidoValidatorFactory.build_active_vals(bs.ref_epoch) for _ in range(2)],
        *[LidoValidatorFactory.build_exit_vals(bs.ref_epoch) for _ in range(2)],
    ]
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=validators)
    accounting.w3.lido_contracts.accounting_oracle.get_consensus_version = Mock(return_value=3)
    accounting.w3.cc.get_config_spec = Mock(return_value=Mock(ELECTRA_FORK_EPOCH=bs.ref_epoch))
    count, balance = accounting._get_consensus_lido_state(bs)

    assert count == 10
    assert balance == sum(val.balance for val in validators)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("post_total_pooled_ether", "post_total_shares", "expected_share_rate"),
    [
        (15 * 10**18, 15 * 10**18, 1 * 10**27),
        (12 * 10**18, 15 * 10**18, 8 * 10**26),
        (18 * 10**18, 14 * 10**18, 1285714285714285714285714285),
    ],
)
def test_get_finalization_data(accounting: Accounting, post_total_pooled_ether, post_total_shares, expected_share_rate):
    lido_rebase = LidoReportRebaseFactory.build(
        post_total_pooled_ether=post_total_pooled_ether,
        post_total_shares=post_total_shares,
    )

    accounting.get_chain_config = Mock(return_value=ChainConfigFactory.build())
    accounting.get_frame_config = Mock(return_value=FrameConfigFactory.build(initial_epoch=2, epochs_per_frame=1))
    accounting.simulate_full_rebase = Mock(return_value=lido_rebase)
    accounting._is_bunker = Mock(return_value=False)

    bs = ReferenceBlockStampFactory.build()

    with patch.object(Withdrawal, '__init__', return_value=None), patch.object(
        Withdrawal, 'get_finalization_batches', return_value=[]
    ):
        share_rate, batches = accounting._get_finalization_data(bs)

    assert batches == []
    assert share_rate == expected_share_rate

    if post_total_pooled_ether > post_total_shares:
        assert share_rate > 10**27
    else:
        assert share_rate <= 10**27


@pytest.mark.unit
# @pytest.mark.usefixtures("contracts")
def test_get_slots_elapsed_from_initialize(accounting: Accounting):
    accounting.get_chain_config = Mock(return_value=ChainConfigFactory.build())
    accounting.get_frame_config = Mock(return_value=FrameConfigFactory.build(initial_epoch=2, epochs_per_frame=1))

    accounting.w3.lido_contracts.get_accounting_last_processing_ref_slot = Mock(return_value=None)

    bs = ReferenceBlockStampFactory.build(ref_slot=100)
    slots_elapsed = accounting._get_slots_elapsed_from_last_report(bs)

    assert slots_elapsed == 100 - 32 * 2 + 1


@pytest.mark.unit
# @pytest.mark.usefixtures("contracts")
def test_get_slots_elapsed_from_last_report(accounting: Accounting):
    accounting.get_chain_config = Mock(return_value=ChainConfigFactory.build())
    accounting.get_frame_config = Mock(return_value=FrameConfigFactory.build(initial_epoch=2, epochs_per_frame=1))

    accounting.w3.lido_contracts.get_accounting_last_processing_ref_slot = Mock(return_value=70)

    bs = ReferenceBlockStampFactory.build(ref_slot=100)
    slots_elapsed = accounting._get_slots_elapsed_from_last_report(bs)

    assert slots_elapsed == 100 - 70


class TestAccountingReportingAllowed:
    def test_env_toggle(self, accounting: Accounting, monkeypatch: pytest.MonkeyPatch, ref_bs: ReferenceBlockStamp):
        accounting._is_bunker = Mock(return_value=True)
        with monkeypatch.context() as ctx:
            ctx.setattr(accounting_module, 'ALLOW_REPORTING_IN_BUNKER_MODE', True)
            assert accounting.is_reporting_allowed(ref_bs)

    def test_no_bunker_mode(self, accounting: Accounting, ref_bs):
        accounting._is_bunker = Mock(return_value=False)
        assert accounting.is_reporting_allowed(ref_bs)

    def test_bunker_mode_active(self, accounting: Accounting, ref_bs: ReferenceBlockStamp):
        accounting._is_bunker = Mock(return_value=True)
        assert accounting.is_reporting_allowed(ref_bs) is variables.ALLOW_REPORTING_IN_BUNKER_MODE


class TestAccountingProcessExtraData:
    @pytest.fixture
    def submit_extra_data_mock(self, accounting: Accounting, monkeypatch: pytest.MonkeyPatch) -> Iterable[Mock]:
        with monkeypatch.context() as m:
            mock = Mock()
            m.setattr(accounting, '_submit_extra_data', mock)
            yield mock

    @pytest.fixture
    def _no_sleep_before_report(self, accounting: Accounting):
        accounting.get_chain_config = Mock(return_value=Mock(seconds_per_slot=0))
        accounting._get_slot_delay_before_data_submit = Mock(return_value=0)

    @pytest.mark.unit
    @pytest.mark.usefixtures('_no_sleep_before_report')
    def test_no_submit_if_can_submit_is_false(
        self,
        accounting: Accounting,
        submit_extra_data_mock: Mock,
        ref_bs: ReferenceBlockStamp,
        bs: BlockStamp,
    ):
        accounting._get_latest_blockstamp = Mock(return_value=bs)
        accounting.can_submit_extra_data = Mock(return_value=False)

        accounting.process_extra_data(ref_bs)

        accounting.can_submit_extra_data.assert_called_once_with(bs)
        submit_extra_data_mock.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.usefixtures('_no_sleep_before_report')
    def test_submit_if_can_submit_is_true(
        self,
        accounting: Accounting,
        submit_extra_data_mock: Mock,
        ref_bs: ReferenceBlockStamp,
        bs: BlockStamp,
    ):
        accounting._get_latest_blockstamp = Mock(return_value=bs)
        accounting.can_submit_extra_data = Mock(return_value=True)

        accounting.process_extra_data(ref_bs)

        assert accounting.can_submit_extra_data.call_count == 2
        assert accounting.can_submit_extra_data.call_args[0][0] is bs
        submit_extra_data_mock.assert_called_once_with(ref_bs)


class TestAccountingSubmitExtraData:
    def test_submit_extra_data_non_empty(
        self,
        accounting: Accounting,
        ref_bs: ReferenceBlockStamp,
        chain_config: ChainConfig,
    ):
        extra_data = bytes(32)

        accounting.w3.lido_contracts.accounting_oracle.get_consensus_version = Mock(return_value=1)
        accounting.get_extra_data = Mock(return_value=Mock(extra_data_list=[extra_data]))
        accounting.report_contract.submit_report_extra_data_list = Mock()  # type: ignore
        accounting.w3.transaction = Mock()

        accounting._submit_extra_data(ref_bs)

        accounting.report_contract.submit_report_extra_data_list.assert_called_once_with(extra_data)
        accounting.get_extra_data.assert_called_once_with(ref_bs)

    @pytest.mark.unit
    def test_submit_extra_data_empty(
        self,
        accounting: Accounting,
        ref_bs: ReferenceBlockStamp,
        chain_config: ChainConfig,
    ):
        accounting.get_extra_data = Mock(return_value=Mock(format=FormatList.EXTRA_DATA_FORMAT_LIST_EMPTY.value))
        accounting.report_contract.submit_report_extra_data_list = Mock()  # type: ignore
        accounting.report_contract.submit_report_extra_data_empty = Mock()  # type: ignore
        accounting.w3.transaction = Mock()

        accounting._submit_extra_data(ref_bs)

        accounting.report_contract.submit_report_extra_data_empty.assert_called_once()
        accounting.report_contract.submit_report_extra_data_list.assert_not_called()
        accounting.get_extra_data.assert_called_once_with(ref_bs)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("main_data_submitted", "extra_data_submitted", "expected"),
    [
        (False, False, False),
        (False, True, False),
        (True, False, True),
        (True, True, False),
    ],
)
def test_can_submit_extra_data(
    accounting: Accounting,
    extra_data_submitted: bool,
    main_data_submitted: bool,
    expected: bool,
    bs: BlockStamp,
):
    accounting.w3.lido_contracts.accounting_oracle.get_processing_state = Mock(
        return_value=Mock(
            extra_data_submitted=extra_data_submitted,
            main_data_submitted=main_data_submitted,
        )
    )

    out = accounting.can_submit_extra_data(bs)

    assert out == expected, "can_submit_extra_data returned unexpected value"
    accounting.w3.lido_contracts.accounting_oracle.get_processing_state.assert_called_once_with(bs.block_hash)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("main_data_submitted", "can_submit_extra_data", "expected"),
    [
        (False, False, True),
        (False, True, True),
        (True, False, False),
        (True, True, True),
    ],
)
def test_is_contract_reportable(
    accounting: Accounting,
    main_data_submitted: bool,
    can_submit_extra_data: bool,
    expected: bool,
    bs: BlockStamp,
):
    accounting.is_main_data_submitted = Mock(return_value=main_data_submitted)
    accounting.can_submit_extra_data = Mock(return_value=can_submit_extra_data)

    out = accounting.is_contract_reportable(bs)

    assert out == expected, "is_contract_reportable returned unexpected value"


@pytest.mark.unit
def test_is_main_data_submitted(
    accounting: Accounting,
    bs: BlockStamp,
):
    accounting.w3.lido_contracts.accounting_oracle.get_processing_state = Mock(
        return_value=Mock(main_data_submitted=False)
    )
    assert accounting.is_main_data_submitted(bs) is False, "is_main_data_submitted returned unexpected value"
    accounting.w3.lido_contracts.accounting_oracle.get_processing_state.assert_called_once_with(bs.block_hash)

    accounting.w3.lido_contracts.accounting_oracle.get_processing_state.reset_mock()

    accounting.w3.lido_contracts.accounting_oracle.get_processing_state = Mock(
        return_value=Mock(main_data_submitted=True)
    )
    assert accounting.is_main_data_submitted(bs) is True, "is_main_data_submitted returned unexpected value"
    accounting.w3.lido_contracts.accounting_oracle.get_processing_state.assert_called_once_with(bs.block_hash)


@pytest.mark.unit
def test_build_report(
    accounting: Accounting,
    ref_bs: ReferenceBlockStamp,
):
    REPORT = object()

    accounting._calculate_report = Mock(return_value=Mock(as_tuple=Mock(return_value=REPORT)))

    report = accounting.build_report(ref_bs)

    assert report is REPORT, "build_report returned unexpected value"
    accounting._calculate_report.assert_called_once_with(ref_bs)

    # @lru_cache
    accounting._calculate_report.reset_mock()
    accounting.build_report(ref_bs)
    accounting._calculate_report.assert_not_called()


@pytest.mark.unit
def test_get_shares_to_burn(
    accounting: Accounting,
    bs: BlockStamp,
    monkeypatch: pytest.MonkeyPatch,
):
    shares_data = Mock(cover_shares=42, non_cover_shares=17)
    call_mock = accounting.w3.lido_contracts.burner.get_shares_requested_to_burn = Mock(return_value=shares_data)

    out = accounting.get_shares_to_burn(bs)

    assert (
        out == shares_data.cover_shares + shares_data.non_cover_shares
    ), "get_shares_to_burn returned unexpected value"
    call_mock.assert_called_once()


@pytest.mark.unit
def test_simulate_cl_rebase(accounting: Accounting, ref_bs: ReferenceBlockStamp):
    RESULT = object()
    accounting.simulate_rebase_after_report = Mock(return_value=RESULT)

    out = accounting.simulate_cl_rebase(ref_bs)

    assert out is RESULT, "simulate_cl_rebase returned unexpected value"
    accounting.simulate_rebase_after_report.assert_called_once_with(ref_bs, el_rewards=0)


@pytest.mark.unit
def test_simulate_full_rebase(accounting: Accounting, ref_bs: ReferenceBlockStamp):
    RESULT = object()
    accounting.simulate_rebase_after_report = Mock(return_value=RESULT)
    accounting.w3.lido_contracts.get_el_vault_balance = Mock(return_value=42)

    out = accounting.simulate_full_rebase(ref_bs)

    assert out is RESULT, "simulate_full_rebase returned unexpected value"
    accounting.simulate_rebase_after_report.assert_called_once_with(ref_bs, el_rewards=42)


@pytest.mark.unit
def test_simulate_rebase_after_report(
    accounting: Accounting,
    ref_bs: ReferenceBlockStamp,
    chain_config: ChainConfig,
):
    # NOTE: we don't test the actual rebase calculation here, just the logic of the method
    accounting.get_chain_config = Mock(return_value=chain_config)
    accounting.w3.lido_contracts.get_withdrawal_balance = Mock(return_value=17)
    accounting.get_shares_to_burn = Mock(return_value=13)

    accounting._get_consensus_lido_state = Mock(return_value=(0, 0))
    accounting._get_slots_elapsed_from_last_report = Mock(return_value=42)

    accounting.w3.lido_contracts.lido.handle_oracle_report = Mock(return_value=LidoReportRebaseFactory.build())  # type: ignore

    out = accounting.simulate_rebase_after_report(ref_bs, Wei(0))
    assert isinstance(out, LidoReportRebase), "simulate_rebase_after_report returned unexpected value"


@pytest.mark.unit
@pytest.mark.usefixtures('lido_validators')
def test_get_newly_exited_validators_by_modules(accounting: Accounting, ref_bs: ReferenceBlockStamp):
    accounting.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[Mock(), Mock()])
    accounting.lido_validator_state_service.get_exited_lido_validators = Mock(return_value=[])

    RESULT = object()
    accounting.get_updated_modules_stats = Mock(return_value=RESULT)

    out = accounting._get_newly_exited_validators_by_modules(ref_bs)

    assert out is RESULT
    accounting.w3.lido_contracts.staking_router.get_staking_modules.assert_called_once_with(ref_bs.block_hash)
    accounting.lido_validator_state_service.get_exited_lido_validators.assert_called_once_with(ref_bs)


@pytest.mark.unit
def test_is_bunker(
    accounting: Accounting,
    ref_bs: ReferenceBlockStamp,
    chain_config: ChainConfig,
    frame_config: FrameConfig,
):
    CL_REBASE = object()
    BUNKER = object()

    accounting.get_frame_config = Mock(return_value=frame_config)
    accounting.get_chain_config = Mock(return_value=chain_config)
    accounting.simulate_cl_rebase = Mock(return_value=CL_REBASE)
    accounting.bunker_service.is_bunker_mode = Mock(return_value=BUNKER)

    out = accounting._is_bunker(ref_bs)
    assert out is BUNKER, "_is_bunker returned unexpected value"

    args = accounting.bunker_service.is_bunker_mode.call_args[0]
    assert ref_bs in args, "is_bunker_mode called with unexpected blockstamp"
    assert frame_config in args, "is_bunker_mode called with unexpected frame_config"
    assert chain_config in args, "is_bunker_mode called with unexpected chain_config"
    assert CL_REBASE in args, "is_bunker_mode called with unexpected cl_rebase_report"

    # @lru_cache
    accounting.bunker_service.is_bunker_mode.reset_mock()
    accounting._is_bunker(ref_bs)
    accounting.bunker_service.is_bunker_mode.assert_not_called()


def test_accounting_get_processing_state_no_yet_init_epoch(accounting: Accounting):
    bs = ReferenceBlockStampFactory.build()

    accounting.report_contract.get_processing_state = Mock(side_effect=ContractCustomError('0xcd0883ea', '0xcd0883ea'))
    accounting.get_initial_or_current_frame = Mock(
        return_value=CurrentFrame(ref_slot=100, report_processing_deadline_slot=200)
    )
    processing_state = accounting._get_processing_state(bs)

    assert isinstance(processing_state, AccountingProcessingState)
    assert processing_state.current_frame_ref_slot == 100
    assert processing_state.processing_deadline_time == 200
    assert processing_state.main_data_submitted == False
    assert processing_state.main_data_hash == ZERO_HASH


def test_accounting_get_processing_state(accounting: Accounting):
    bs = ReferenceBlockStampFactory.build()
    accounting_processing_state = AccountingProcessingStateFactory.build()
    accounting.report_contract.get_processing_state = Mock(return_value=accounting_processing_state)
    result = accounting._get_processing_state(bs)

    assert accounting_processing_state == result
