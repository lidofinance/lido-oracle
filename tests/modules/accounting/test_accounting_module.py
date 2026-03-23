from collections.abc import Iterable
from typing import cast
from unittest.mock import Mock, patch

import pytest
from web3.exceptions import ContractCustomError
from web3.types import Wei

from src import variables
from src.modules.common.types import (
    ZERO_HASH,
    ChainConfig,
    CurrentFrame,
    FrameConfig,
    ModuleExecuteDelay,
)
from src.modules.oracles.accounting import accounting as accounting_module
from src.modules.oracles.accounting.accounting import Accounting, logger as accounting_logger
from src.modules.oracles.accounting.third_phase.extra_data import ExtraDataService
from src.modules.oracles.accounting.third_phase.types import FormatList
from src.modules.oracles.accounting.types import (
    AccountingProcessingState,
    FinalizationShareRate,
    ReportData,
    ReportSimulationFeeDistribution,
    ReportSimulationPayload,
    ReportSimulationResults,
    Shares,
    VaultsTreeCid,
    VaultsTreeRoot,
)
from src.services.withdrawal import Withdrawal
from src.types import BlockStamp, Gwei, ReferenceBlockStamp, StakingModuleId
from src.web3py.extensions.lido_validators import NodeOperatorId, StakingModule
from tests.factory.base_oracle import AccountingProcessingStateFactory
from tests.factory.blockstamp import BlockStampFactory, ReferenceBlockStampFactory
from tests.factory.configs import ChainConfigFactory, FrameConfigFactory
from tests.factory.contract_responses import ReportSimulationResultsFactory
from tests.factory.no_registry import LidoValidatorFactory, StakingModuleFactory


@pytest.fixture(autouse=True)
def silence_logger() -> None:
    accounting_logger.disabled = True


@pytest.fixture
def accounting(web3):
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
    assert accounting.execute_module(last_finalized_blockstamp=bs) is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH, (
        "execute_module should wait for the next finalized epoch"
    )
    accounting.get_blockstamp_for_report.assert_called_once_with(bs)

    accounting.get_blockstamp_for_report = Mock(return_value=bs)
    accounting.process_report = Mock(return_value=None)
    accounting.process_extra_data = Mock(return_value=None)
    accounting._check_compatibility = Mock(return_value=True)
    assert accounting.execute_module(last_finalized_blockstamp=bs) is ModuleExecuteDelay.NEXT_SLOT, (
        "execute_module should wait for the next slot"
    )
    accounting.get_blockstamp_for_report.assert_called_once_with(bs)
    accounting.process_report.assert_called_once_with(bs)
    accounting.process_extra_data.assert_called_once_with(bs)


@pytest.mark.unit
def test_get_newly_exited_validators_by_modules_stats(accounting: Accounting, ref_bs: ReferenceBlockStamp):
    staking_modules: list[StakingModule] = [
        StakingModuleFactory.build(id=1, exited_validators_count=10),
        StakingModuleFactory.build(id=2, exited_validators_count=20),
        StakingModuleFactory.build(id=3, exited_validators_count=30),
    ]

    exited_validators_stats = {
        (staking_modules[0].id, NodeOperatorId(0)): 10,
        (staking_modules[1].id, NodeOperatorId(0)): 25,
        (staking_modules[2].id, NodeOperatorId(0)): 30,
    }

    accounting.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=staking_modules)
    accounting.lido_validator_state_service.get_exited_lido_validators = Mock(return_value=exited_validators_stats)

    module_ids, exited_validators_count_list = accounting._get_newly_exited_validators_by_modules(ref_bs)

    assert len(module_ids) == 1
    assert module_ids[0] == staking_modules[1].id
    assert exited_validators_count_list[0] == 25


@pytest.mark.unit
def test_get_cl_validators_balance(accounting: Accounting):
    bs = ReferenceBlockStampFactory.build()
    validators = LidoValidatorFactory.batch(10)
    accounting.w3.lido_validators.get_active_lido_validators = Mock(return_value=validators)

    balance = accounting._get_cl_validators_balance(bs)

    assert balance == sum(val.balance for val in validators)


@pytest.mark.unit
def test_get_cl_pending_validators_balance(accounting: Accounting):
    bs = ReferenceBlockStampFactory.build()

    # Mock pending validators data structure
    pending_validators_data = {
        'key1': ('wc1', [Mock(amount=1000), Mock(amount=2000)]),
        'key2': ('wc2', [Mock(amount=3000)]),
    }
    accounting.w3.lido_validators.get_pending_lido_validators = Mock(return_value=pending_validators_data)

    balance = accounting._get_cl_pending_validators_balance(bs)

    assert balance == 6000


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
    lido_rebase = ReportSimulationResultsFactory.build(
        post_total_pooled_ether=post_total_pooled_ether,
        post_total_shares=post_total_shares,
        withdrawals_vault_transfer=Wei(10),
        el_rewards_vault_transfer=Wei(10),
        ether_to_finalize_wq=0,
        shares_to_finalize_wq=0,
        shares_to_burn_for_withdrawals=0,
        total_shares_to_burn=0,
        shares_to_mint_as_fees=0,
        fee_distribution=ReportSimulationFeeDistribution(
            module_fee_recipients=[],
            module_ids=[],
            module_shares_to_mint=0,
            treasury_shares_to_mint=0,
        ),
        principal_cl_balance=0,
        post_internal_shares=0,
        post_internal_ether=0,
    )

    accounting.get_chain_config = Mock(return_value=ChainConfigFactory.build())
    accounting.get_frame_config = Mock(return_value=FrameConfigFactory.build(initial_epoch=2, epochs_per_frame=1))
    accounting.simulate_full_rebase = Mock(return_value=lido_rebase)
    accounting._is_bunker = Mock(return_value=False)

    bs = ReferenceBlockStampFactory.build()

    with (
        patch.object(Withdrawal, '__init__', return_value=None),
        patch.object(Withdrawal, 'get_finalization_batches', return_value=[]),
    ):
        batches, share_rate = accounting._get_finalization_data(bs)

    assert batches == []
    assert share_rate == expected_share_rate

    if post_total_pooled_ether > post_total_shares:
        assert share_rate > 10**27
    else:
        assert share_rate <= 10**27


@pytest.mark.unit
def test_get_slots_elapsed_from_initialize(accounting: Accounting):
    accounting.get_chain_config = Mock(return_value=ChainConfigFactory.build())
    accounting.get_frame_config = Mock(return_value=FrameConfigFactory.build(initial_epoch=2, epochs_per_frame=1))

    accounting.w3.lido_contracts.get_accounting_last_processing_ref_slot = Mock(return_value=None)

    bs = ReferenceBlockStampFactory.build(ref_slot=100)
    slots_elapsed = accounting._get_slots_elapsed_from_last_report(bs)

    # Ref slot of Frame -1.
    # (initial_epoch - epochs_per_frame) * slots_per_epoch - 1
    prev_slot = (2 - 1) * 32 - 1  # 31
    assert slots_elapsed == bs.ref_slot - prev_slot

    accounting.get_frame_config = Mock(return_value=FrameConfigFactory.build(initial_epoch=2, epochs_per_frame=4))

    slots_elapsed = accounting._get_slots_elapsed_from_last_report(bs)
    assert slots_elapsed == bs.ref_slot


@pytest.mark.unit
def test_get_slots_elapsed_from_last_report(accounting: Accounting):
    accounting.get_chain_config = Mock(return_value=ChainConfigFactory.build())
    accounting.get_frame_config = Mock(return_value=FrameConfigFactory.build(initial_epoch=2, epochs_per_frame=1))

    accounting.w3.lido_contracts.get_accounting_last_processing_ref_slot = Mock(return_value=70)

    bs = ReferenceBlockStampFactory.build(ref_slot=100)
    slots_elapsed = accounting._get_slots_elapsed_from_last_report(bs)

    assert slots_elapsed == 100 - 70


@pytest.mark.unit
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

    @pytest.mark.unit
    @pytest.mark.usefixtures('_no_sleep_before_report')
    def test_second_can_submit_check_blocks_submission(
        self,
        accounting: Accounting,
        submit_extra_data_mock: Mock,
        ref_bs: ReferenceBlockStamp,
        bs: BlockStamp,
    ):
        accounting._get_latest_blockstamp = Mock(return_value=bs)
        # First check passes, second check (after sleep) fails
        accounting.can_submit_extra_data = Mock(side_effect=[True, False])

        accounting.process_extra_data(ref_bs)

        assert accounting.can_submit_extra_data.call_count == 2
        submit_extra_data_mock.assert_not_called()


@pytest.mark.unit
class TestAccountingSubmitExtraData:
    def test_submit_extra_data_non_empty(
        self,
        accounting: Accounting,
        ref_bs: ReferenceBlockStamp,
        chain_config: ChainConfig,
    ):
        extra_data = bytes(32)

        accounting.w3.lido_contracts.accounting_oracle.get_consensus_version = Mock(return_value=3)
        accounting.get_extra_data = Mock(return_value=Mock(extra_data_list=[extra_data]))
        accounting.report_contract.submit_report_extra_data_list = Mock()  # type: ignore
        accounting.w3.transaction = Mock()

        accounting._submit_extra_data(ref_bs)

        accounting.report_contract.submit_report_extra_data_list.assert_called_once_with(extra_data)
        accounting.get_extra_data.assert_called_once_with(ref_bs)

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

    assert out == shares_data.cover_shares + shares_data.non_cover_shares, (
        "get_shares_to_burn returned unexpected value"
    )
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

    # Mock the balance methods instead of dealing with validator mocking
    accounting._get_cl_validators_balance = Mock(return_value=Gwei(0))
    accounting._get_cl_pending_validators_balance = Mock(return_value=Gwei(0))
    accounting._get_slots_elapsed_from_last_report = Mock(return_value=42)

    accounting.w3.lido_contracts.accounting = Mock()

    accounting.w3.lido_contracts.accounting.simulate_oracle_report = Mock(
        return_value=ReportSimulationResults(
            withdrawals_vault_transfer=Wei(0),
            el_rewards_vault_transfer=Wei(0),
            ether_to_finalize_wq=Wei(0),
            shares_to_finalize_wq=0,
            shares_to_burn_for_withdrawals=0,
            total_shares_to_burn=0,
            shares_to_mint_as_fees=0,
            fee_distribution=ReportSimulationFeeDistribution(
                module_fee_recipients=[],
                module_ids=[],
                module_shares_to_mint=[],
                treasury_shares_to_mint=0,
            ),
            principal_cl_balance=Wei(0),
            post_internal_shares=0,
            post_internal_ether=Wei(0),
            post_total_shares=0,
            post_total_pooled_ether=Wei(0),
            pre_total_shares=0,
            pre_total_pooled_ether=Wei(0),
        )
    )

    out = accounting.simulate_rebase_after_report(ref_bs, Wei(0))
    accounting.w3.lido_contracts.accounting.simulate_oracle_report.assert_called_once_with(
        ReportSimulationPayload(
            timestamp=1678794852,
            time_elapsed=504,
            cl_validators_balance=Wei(0),
            cl_pending_balance=Wei(0),
            withdrawal_vault_balance=Wei(17),
            el_rewards_vault_balance=Wei(0),
            shares_requested_to_burn=Shares(13),
            withdrawal_finalization_batches=[],
            simulated_share_rate=0,
        ),
        '0x0d339fdfa3018561311a39bf00568ed08048055082448d17091d5a4dc2fa035b',
    )
    assert isinstance(out, ReportSimulationResults), "simulate_rebase_after_report returned unexpected value"


@pytest.mark.unit
def test_get_newly_exited_validators_by_modules_empty(accounting: Accounting, ref_bs: ReferenceBlockStamp):
    staking_modules = [
        StakingModuleFactory.build(id=1, exited_validators_count=0),
        StakingModuleFactory.build(id=2, exited_validators_count=0),
    ]
    accounting.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=staking_modules)
    accounting.lido_validator_state_service.get_exited_lido_validators = Mock(return_value={})

    module_ids, exited_validators_count_list = accounting._get_newly_exited_validators_by_modules(ref_bs)

    assert module_ids == []
    assert exited_validators_count_list == []
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


@pytest.mark.unit
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
    assert processing_state.main_data_submitted is False
    assert processing_state.main_data_hash == ZERO_HASH


@pytest.mark.unit
def test_accounting_get_processing_state(accounting: Accounting):
    bs = ReferenceBlockStampFactory.build()
    accounting_processing_state = AccountingProcessingStateFactory.build()
    accounting.report_contract.get_processing_state = Mock(return_value=accounting_processing_state)
    result = accounting._get_processing_state(bs)

    assert accounting_processing_state == result


# ---- refresh_contracts / is_contracts_addresses_changed ----


@pytest.mark.unit
def test_refresh_contracts(accounting: Accounting):
    new_contract = Mock()
    accounting.w3.lido_contracts.accounting_oracle = new_contract
    accounting.refresh_contracts()
    assert accounting.report_contract is new_contract


@pytest.mark.unit
def test_is_contracts_addresses_changed(accounting: Accounting):
    accounting.w3.lido_contracts.has_contract_address_changed = Mock(return_value=True)
    assert accounting.is_contracts_addresses_changed() is True

    accounting.w3.lido_contracts.has_contract_address_changed = Mock(return_value=False)
    assert accounting.is_contracts_addresses_changed() is False


# ---- execute_module: _check_compatibility returns False ----


@pytest.mark.unit
def test_accounting_execute_module_compatibility_fails(accounting: Accounting, bs: BlockStamp):
    accounting.get_blockstamp_for_report = Mock(return_value=bs)
    accounting._check_compatibility = Mock(return_value=False)
    assert accounting.execute_module(last_finalized_blockstamp=bs) is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH
    accounting.get_blockstamp_for_report.assert_called_once_with(bs)


# ---- _get_processing_state: non-matching ContractCustomError re-raises ----


@pytest.mark.unit
def test_accounting_get_processing_state_unknown_error_reraises(accounting: Accounting):
    bs = ReferenceBlockStampFactory.build()
    accounting.report_contract.get_processing_state = Mock(side_effect=ContractCustomError('0xdeadbeef', '0xdeadbeef'))
    with pytest.raises(ContractCustomError):
        accounting._get_processing_state(bs)


# ---- _get_finalization_data: post_total_shares == 0 → share_rate == 0 ----


@pytest.mark.unit
def test_get_finalization_data_zero_shares(accounting: Accounting):
    lido_rebase = ReportSimulationResultsFactory.build(
        post_total_pooled_ether=10**18,
        post_total_shares=0,
        withdrawals_vault_transfer=Wei(0),
        el_rewards_vault_transfer=Wei(0),
        ether_to_finalize_wq=0,
        shares_to_finalize_wq=0,
        shares_to_burn_for_withdrawals=0,
        total_shares_to_burn=0,
        shares_to_mint_as_fees=0,
        fee_distribution=ReportSimulationFeeDistribution(
            module_fee_recipients=[],
            module_ids=[],
            module_shares_to_mint=0,
            treasury_shares_to_mint=0,
        ),
        principal_cl_balance=0,
        post_internal_shares=0,
        post_internal_ether=0,
    )
    accounting.get_chain_config = Mock(return_value=ChainConfigFactory.build())
    accounting.get_frame_config = Mock(return_value=FrameConfigFactory.build(initial_epoch=2, epochs_per_frame=1))
    accounting.simulate_full_rebase = Mock(return_value=lido_rebase)
    accounting._is_bunker = Mock(return_value=False)

    bs = ReferenceBlockStampFactory.build()
    with (
        patch.object(Withdrawal, '__init__', return_value=None),
        patch.object(Withdrawal, 'get_finalization_batches', return_value=[]),
    ):
        _, share_rate = accounting._get_finalization_data(bs)

    assert share_rate == 0


# ---- _get_cl_pending_validators_balance: empty input ----


@pytest.mark.unit
def test_get_cl_pending_validators_balance_empty(accounting: Accounting):
    bs = ReferenceBlockStampFactory.build()
    accounting.w3.lido_validators.get_pending_lido_validators = Mock(return_value={})
    balance = accounting._get_cl_pending_validators_balance(bs)
    assert balance == 0


# ---- _get_newly_exited_validators_by_modules: multiple operators per module are summed ----


@pytest.mark.unit
def test_get_newly_exited_validators_by_modules_multi_operators(accounting: Accounting, ref_bs: ReferenceBlockStamp):
    staking_modules = [StakingModuleFactory.build(id=1, exited_validators_count=5)]
    exited_validators_stats = {
        (staking_modules[0].id, NodeOperatorId(0)): 3,
        (staking_modules[0].id, NodeOperatorId(1)): 4,
    }
    accounting.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=staking_modules)
    accounting.lido_validator_state_service.get_exited_lido_validators = Mock(return_value=exited_validators_stats)

    module_ids, exited_count_list = accounting._get_newly_exited_validators_by_modules(ref_bs)

    assert module_ids == [staking_modules[0].id]
    assert exited_count_list == [7]  # 3 + 4 operators summed


# ---- _get_balances_by_modules ----


@pytest.mark.unit
def test_get_balances_by_modules(accounting: Accounting, ref_bs: ReferenceBlockStamp):
    balances_by_no = {
        (StakingModuleId(1), NodeOperatorId(0)): {'active': Gwei(100), 'pending': Gwei(50)},
        (StakingModuleId(1), NodeOperatorId(1)): {'active': Gwei(200), 'pending': Gwei(30)},
        (StakingModuleId(2), NodeOperatorId(0)): {'active': Gwei(300), 'pending': Gwei(70)},
    }
    accounting._get_no_active_balance = Mock(return_value=balances_by_no)

    sm_ids, active_balances, pending_balances = accounting._get_balances_by_modules(ref_bs)

    assert sm_ids == [StakingModuleId(1), StakingModuleId(2)]
    assert active_balances == [Gwei(300), Gwei(300)]
    assert pending_balances == [Gwei(80), Gwei(70)]


# ---- _get_no_active_balance ----


@pytest.mark.unit
def test_get_no_active_balance(accounting: Accounting, ref_bs: ReferenceBlockStamp):
    module_address = '0x' + 'ab' * 20
    module_id = StakingModuleId(1)
    operator_index = 0
    gid = (module_id, operator_index)
    pubkey = '0xdeadbeef'

    validator = Mock()
    validator.validator.pubkey = pubkey
    validator.balance = 100

    module = Mock()
    module.staking_module_address = module_address
    module.id = module_id

    lido_key = Mock()
    lido_key.moduleAddress = module_address
    lido_key.operatorIndex = operator_index
    new_deposit = Mock(amount=32_000_000_000)

    topup_deposit = Mock(pubkey=pubkey, amount=1_000_000_000)
    unknown_deposit = Mock(pubkey='0xunknown', amount=999)

    accounting.w3.lido_validators.get_lido_validators_by_node_operators = Mock(return_value={gid: [validator]})
    accounting.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[module])
    accounting.w3.lido_validators.get_pending_lido_validators = Mock(return_value={'key1': (lido_key, [new_deposit])})
    accounting.w3.cc.get_pending_deposits = Mock(return_value=[topup_deposit, unknown_deposit])
    accounting.w3.cc.get_pending_consolidations = Mock(return_value=[topup_deposit, unknown_deposit])

    result = accounting._get_no_active_balance(ref_bs)

    assert result[gid]['active'] == 100
    assert result[gid]['pending'] == new_deposit.amount + topup_deposit.amount
    # Unknown pubkey should not contribute to any existing operator's pending balance
    assert result.get(('0xunknown', 0)) is None


# ---- get_extra_data ----


@pytest.mark.unit
def test_get_extra_data(accounting: Accounting, ref_bs: ReferenceBlockStamp):
    exited_validators = {(StakingModuleId(1), NodeOperatorId(0)): 5}
    accounting.lido_validator_state_service.get_lido_newly_exited_validators = Mock(return_value=exited_validators)
    orl = Mock(max_items_per_extra_data_transaction=10, max_node_operators_per_extra_data_item=20)
    accounting.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits = Mock(return_value=orl)

    expected_result = Mock()
    with patch.object(ExtraDataService, 'collect', return_value=expected_result) as mock_collect:
        result = accounting.get_extra_data(ref_bs)

    assert result is expected_result
    mock_collect.assert_called_once_with(exited_validators, 10, 20)


# ---- _handle_vaults_report ----


@pytest.mark.unit
def test_handle_vaults_report_empty_vaults(accounting: Accounting, ref_bs: ReferenceBlockStamp):
    accounting.staking_vaults.get_vaults = Mock(return_value={})

    tree_root, tree_cid = accounting._handle_vaults_report(ref_bs)

    assert tree_root == ZERO_HASH
    assert tree_cid == ''


@pytest.mark.unit
def test_handle_vaults_report_non_empty_vaults(
    accounting: Accounting,
    ref_bs: ReferenceBlockStamp,
    chain_config: ChainConfig,
    frame_config: FrameConfig,
):
    vault_addr = '0x' + '11' * 20
    vaults = {vault_addr: Mock()}
    tree_root_bytes = b'\x01' * 32
    tree_cid_str = 'QmTest'

    merkle_tree = Mock()
    merkle_tree.root = tree_root_bytes

    simulation = Mock(
        pre_total_pooled_ether=1000,
        pre_total_shares=1000,
        post_internal_ether=1010,
        post_internal_shares=1000,
        shares_to_mint_as_fees=0,
    )

    accounting.staking_vaults.get_vaults = Mock(return_value=vaults)
    accounting.get_frame_number_by_slot = Mock(return_value=10)
    accounting.w3.cc.get_validators = Mock(return_value=[])
    accounting.w3.cc.get_pending_deposits = Mock(return_value=[])
    accounting.get_chain_config = Mock(return_value=chain_config)
    accounting.get_frame_config = Mock(return_value=frame_config)
    accounting.simulate_full_rebase = Mock(return_value=simulation)
    accounting.staking_vaults.get_vaults_total_values = Mock(return_value={vault_addr: Wei(100)})
    accounting._get_slots_elapsed_from_last_report = Mock(return_value=100)
    accounting.staking_vaults.get_latest_onchain_ipfs_report_data = Mock(return_value=Mock(report_cid='QmPrev'))
    accounting.staking_vaults.get_vaults_fees = Mock(return_value={})
    accounting.staking_vaults.get_vaults_slashing_reserve = Mock(return_value={})
    accounting.staking_vaults.build_tree_data = Mock(return_value=[])
    accounting.staking_vaults.get_merkle_tree = Mock(return_value=merkle_tree)
    accounting.staking_vaults.publish_tree = Mock(return_value=tree_cid_str)

    with (
        patch('src.modules.oracles.accounting.accounting.calculate_gross_core_apr', return_value=0.05),
        patch('src.modules.oracles.accounting.accounting.VAULTS_TOTAL_VALUE'),
    ):
        result_root, result_cid = accounting._handle_vaults_report(ref_bs)

    assert result_root == tree_root_bytes
    assert result_cid == tree_cid_str
    accounting.staking_vaults.get_merkle_tree.assert_called_once()
    accounting.staking_vaults.publish_tree.assert_called_once()


# ---- _update_metrics ----


@pytest.mark.unit
def test_update_metrics():
    report_data = Mock(
        is_bunker=True,
        cl_pending_balance_gwei=100,
        cl_validators_balance_gwei=200,
        withdrawal_vault_balance=300,
        el_rewards_vault_balance=400,
    )
    with (
        patch('src.modules.oracles.accounting.accounting.ACCOUNTING_IS_BUNKER') as mock_bunker,
        patch('src.modules.oracles.accounting.accounting.ACCOUNTING_BALANCE_GWEI') as mock_balance,
    ):
        Accounting._update_metrics(report_data)

    mock_bunker.set.assert_called_once_with(True)
    mock_balance.labels.assert_any_call('pending')
    mock_balance.labels.assert_any_call('active')
    mock_balance.labels.assert_any_call('withdrawal_vault')
    mock_balance.labels.assert_any_call('el_reward_vault')


# ---- _calculate_report ----


@pytest.mark.unit
def test_calculate_report(accounting: Accounting, ref_bs: ReferenceBlockStamp):
    accounting.get_consensus_version = Mock(return_value=6)
    accounting._get_cl_validators_balance = Mock(return_value=Gwei(1000))
    accounting._get_cl_pending_validators_balance = Mock(return_value=Gwei(500))
    accounting._get_newly_exited_validators_by_modules = Mock(return_value=([StakingModuleId(1)], [5]))
    accounting._get_balances_by_modules = Mock(return_value=([StakingModuleId(1)], [Gwei(1000)], [Gwei(500)]))
    accounting.w3.lido_contracts.get_withdrawal_balance = Mock(return_value=Wei(100))
    accounting.w3.lido_contracts.get_el_vault_balance = Mock(return_value=Wei(200))
    accounting.get_shares_to_burn = Mock(return_value=Shares(10))
    accounting._get_finalization_data = Mock(return_value=([], FinalizationShareRate(10**27)))
    accounting._is_bunker = Mock(return_value=False)
    accounting._handle_vaults_report = Mock(return_value=(VaultsTreeRoot(ZERO_HASH), VaultsTreeCid('')))
    accounting.get_extra_data = Mock(return_value=Mock(format=0, data_hash=bytes(32), items_count=0))

    with (
        patch('src.modules.oracles.accounting.accounting.ACCOUNTING_IS_BUNKER'),
        patch('src.modules.oracles.accounting.accounting.ACCOUNTING_BALANCE_GWEI'),
    ):
        report_data = accounting._calculate_report(ref_bs)

    assert isinstance(report_data, ReportData)
    assert report_data.consensus_version == 6
    assert report_data.ref_slot == ref_bs.ref_slot
    assert report_data.cl_validators_balance_gwei == 1000
    assert report_data.cl_pending_balance_gwei == 500
    assert report_data.staking_module_ids_with_exited_validators == [StakingModuleId(1)]
    assert report_data.count_exited_validators_by_staking_module == [5]
    assert report_data.withdrawal_vault_balance == 100
    assert report_data.el_rewards_vault_balance == 200
    assert report_data.is_bunker is False
    accounting.get_consensus_version.assert_called_once_with(ref_bs)
    accounting._get_cl_validators_balance.assert_called_once_with(ref_bs)
    accounting._get_cl_pending_validators_balance.assert_called_once_with(ref_bs)
