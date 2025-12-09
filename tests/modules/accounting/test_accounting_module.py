from typing import Iterable, cast
from unittest.mock import Mock, patch

import pytest
from eth_typing import ChecksumAddress, HexAddress, HexStr
from web3.exceptions import ContractCustomError
from web3.types import Wei

from src import variables
from src.modules.accounting import accounting as accounting_module
from src.modules.accounting.accounting import Accounting, logger as accounting_logger
from src.modules.accounting.third_phase.types import FormatList
from src.modules.accounting.types import (
    AccountingProcessingState,
    ReportSimulationFeeDistribution,
    ReportSimulationPayload,
    ReportSimulationResults,
    VaultInfo,
    VaultsData,
    VaultsMap,
    VaultTreeNode,
)
from src.modules.submodules.oracle_module import ModuleExecuteDelay
from src.modules.submodules.types import (
    ZERO_HASH,
    ChainConfig,
    CurrentFrame,
    FrameConfig,
)
from src.providers.consensus.types import Validator, ValidatorState
from src.services.staking_vaults import StakingVaultsService
from src.services.withdrawal import Withdrawal
from src.types import BlockStamp, EpochNumber, Gwei, ReferenceBlockStamp, ValidatorIndex
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
    assert (
        accounting.execute_module(last_finalized_blockstamp=bs) is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH
    ), "execute_module should wait for the next finalized epoch"
    accounting.get_blockstamp_for_report.assert_called_once_with(bs)

    accounting.get_blockstamp_for_report = Mock(return_value=bs)
    accounting.process_report = Mock(return_value=None)
    accounting.process_extra_data = Mock(return_value=None)
    accounting._check_compatability = Mock(return_value=True)
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
def test_get_consensus_lido_state_pre_electra(accounting: Accounting):
    bs = ReferenceBlockStampFactory.build()
    validators = LidoValidatorFactory.batch(10)
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=validators)

    accounting.w3.lido_contracts.accounting_oracle.get_consensus_version = Mock(return_value=3)
    count, balance = accounting._get_consensus_lido_state(bs)

    assert count == 10
    assert balance == sum(val.balance for val in validators)


@pytest.mark.unit
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

    with patch.object(Withdrawal, '__init__', return_value=None), patch.object(
        Withdrawal, 'get_finalization_batches', return_value=[]
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

    assert slots_elapsed == 100 - 32 * 2 + 1


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

    validators: list[Validator] = [
        Validator(
            index=ValidatorIndex(1985),
            balance=Gwei(32834904184),
            validator=ValidatorState(
                pubkey='0x862d53d9e4313374d202f2b28e6ffe64efb0312f9c2663f2eef67b72345faa8932b27f9b9bb7b476d9b5e418fea99124',
                withdrawal_credentials='0x020000000000000000000000ecb7c8d2baf7270f90066b4cd8286e2ca1154f60',
                effective_balance=Gwei(32000000000),
                slashed=False,
                activation_eligibility_epoch=EpochNumber(225469),
                activation_epoch=EpochNumber(225475),
                exit_epoch=EpochNumber(18446744073709551615),
                withdrawable_epoch=EpochNumber(18446744073709551615),
            ),
        ),
        Validator(
            index=ValidatorIndex(1986),
            balance=Gwei(0),
            validator=ValidatorState(
                pubkey='0xa5d9411ef615c74c9240634905d5ddd46dc40a87a09e8cc0332afddb246d291303e452a850917eefe09b3b8c70a307ce',
                withdrawal_credentials='0x020000000000000000000000ecb7c8d2baf7270f90066b4cd8286e2ca1154f60',
                effective_balance=Gwei(0),
                slashed=False,
                activation_eligibility_epoch=EpochNumber(226130),
                activation_epoch=EpochNumber(226136),
                exit_epoch=EpochNumber(227556),
                withdrawable_epoch=EpochNumber(227812),
            ),
        ),
    ]
    accounting.w3.cc = Mock()
    accounting.w3.cc.get_validators = Mock(return_value=validators)

    tree_data: list[VaultTreeNode] = [
        (
            '0xEcB7C8D2BaF7270F90066B4cd8286e2CA1154F60',
            99786510875371698360,
            33000000000000000000,
            33000000000000000000,
            0,
            0,
        ),
        (
            '0xc1F9c4a809cbc6Cb2cA60bCa09cE9A55bD5337Db',
            2500000000000000000,
            2500000000000000000,
            2500000000000000000,
            0,
            1,
        ),
    ]
    vaults: VaultsMap = {
        ChecksumAddress(HexAddress(HexStr('0xEcB7C8D2BaF7270F90066B4cd8286e2CA1154F60'))): VaultInfo(
            aggregated_balance=Wei(66951606691371698360),
            in_out_delta=Wei(33000000000000000000),
            liability_shares=0,
            max_liability_shares=0,
            vault='0xEcB7C8D2BaF7270F90066B4cd8286e2CA1154F60',
            withdrawal_credentials='0x020000000000000000000000ecb7c8d2baf7270f90066b4cd8286e2ca1154f60',
            share_limit=0,
            reserve_ratio_bp=0,
            forced_rebalance_threshold_bp=0,
            infra_fee_bp=0,
            liquidity_fee_bp=0,
            reservation_fee_bp=0,
            pending_disconnect=False,
            mintable_st_eth=0,
        ),
        ChecksumAddress(HexAddress(HexStr('0xc1F9c4a809cbc6Cb2cA60bCa09cE9A55bD5337Db'))): VaultInfo(
            aggregated_balance=Wei(2500000000000000000),
            in_out_delta=Wei(2500000000000000000),
            liability_shares=1,
            max_liability_shares=1,
            vault='0xc1F9c4a809cbc6Cb2cA60bCa09cE9A55bD5337Db',
            withdrawal_credentials='0x020000000000000000000000c1f9c4a809cbc6cb2ca60bca09ce9a55bd5337db',
            share_limit=0,
            reserve_ratio_bp=0,
            forced_rebalance_threshold_bp=0,
            infra_fee_bp=0,
            liquidity_fee_bp=0,
            reservation_fee_bp=0,
            pending_disconnect=False,
            mintable_st_eth=0,
        ),
    }
    vaults_total_values = {}
    mock_vaults_data: VaultsData = (tree_data, vaults, vaults_total_values)
    accounting.w3.staking_vaults = Mock()
    accounting.w3.staking_vaults.get_vaults_data = Mock(return_value=mock_vaults_data)
    accounting.w3.staking_vaults.publish_proofs = Mock(return_value='proof_cid')
    accounting.w3.staking_vaults.publish_tree = Mock(return_value='tree_cid')
    accounting.w3.staking_vaults.get_merkle_tree = Mock(return_value=StakingVaultsService.get_merkle_tree(tree_data))

    accounting._get_consensus_lido_state = Mock(return_value=(0, 0))
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
            cl_validators=0,
            cl_balance=Wei(0),
            withdrawal_vault_balance=Wei(17),
            el_rewards_vault_balance=Wei(0),
            shares_requested_to_burn=13,
            withdrawal_finalization_batches=[],
            simulated_share_rate=0,
        ),
        '0x0d339fdfa3018561311a39bf00568ed08048055082448d17091d5a4dc2fa035b',
    )
    assert isinstance(out, ReportSimulationResults), "simulate_rebase_after_report returned unexpected value"


@pytest.mark.unit
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
