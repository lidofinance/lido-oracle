import logging
from collections import defaultdict
from time import sleep

from hexbytes import HexBytes
from web3.exceptions import ContractCustomError
from web3.types import Wei

from src import variables
from src.constants import SHARE_RATE_PRECISION_E27
from src.metrics.prometheus.accounting import (
    ACCOUNTING_IS_BUNKER,
    ACCOUNTING_CL_BALANCE_GWEI,
    ACCOUNTING_EL_REWARDS_VAULT_BALANCE_WEI,
    ACCOUNTING_WITHDRAWAL_VAULT_BALANCE_WEI
)
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.accounting.third_phase.extra_data import ExtraDataService
from src.modules.accounting.third_phase.types import ExtraData, FormatList
from src.modules.accounting.types import (
    ReportData,
    LidoReportRebase,
    GenericExtraData,
    WqReport,
    RebaseReport,
    BunkerMode,
    FinalizationShareRate,
    ValidatorsCount,
    ValidatorsBalance,
    AccountingProcessingState,
)
from src.modules.submodules.consensus import ConsensusModule, InitialEpochIsYetToArriveRevert
from src.modules.submodules.oracle_module import BaseModule, ModuleExecuteDelay
from src.modules.submodules.types import ZERO_HASH
from src.providers.execution.contracts.accounting_oracle import AccountingOracleContract
from src.services.bunker import BunkerService
from src.services.validator_state import LidoValidatorStateService
from src.services.withdrawal import Withdrawal
from src.types import BlockStamp, Gwei, ReferenceBlockStamp, StakingModuleId, NodeOperatorGlobalIndex, FinalizationBatches
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.units import gwei_to_wei
from src.variables import ALLOW_REPORTING_IN_BUNKER_MODE
from src.web3py.extensions.lido_validators import StakingModule
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


class Accounting(BaseModule, ConsensusModule):
    """
    Accounting module updates the protocol TVL, distributes node-operator rewards, and processes user withdrawal requests.

    Report goes in tree phases:
        - Send report hash
        - Send report data (with extra data hash inside)
            Contains information about lido state, withdrawal requests to finalize and exited validators count by module.
        - Send extra data
            Contains stuck and exited validator's updates count by each node operator.
    """
    COMPATIBLE_CONTRACT_VERSION = 2
    COMPATIBLE_CONSENSUS_VERSION = 3

    def __init__(self, w3: Web3):
        self.report_contract: AccountingOracleContract = w3.lido_contracts.accounting_oracle
        super().__init__(w3)

        self.lido_validator_state_service = LidoValidatorStateService(self.w3)
        self.bunker_service = BunkerService(self.w3)

    def refresh_contracts(self):
        self.report_contract = self.w3.lido_contracts.accounting_oracle  # type: ignore

    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        report_blockstamp = self.get_blockstamp_for_report(last_finalized_blockstamp)

        if not report_blockstamp:
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        if not self._check_compatability(report_blockstamp):
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        self.process_report(report_blockstamp)
        # Third phase of report. Specific for accounting.
        self.process_extra_data(report_blockstamp)
        return ModuleExecuteDelay.NEXT_SLOT

    def process_extra_data(self, blockstamp: ReferenceBlockStamp):
        latest_blockstamp = self._get_latest_blockstamp()
        if not self.can_submit_extra_data(latest_blockstamp):
            logger.info({'msg': 'Extra data can not be submitted.'})
            return

        chain_config = self.get_chain_config(blockstamp)
        slots_to_sleep = self._get_slot_delay_before_data_submit(latest_blockstamp)
        seconds_to_sleep = slots_to_sleep * chain_config.seconds_per_slot
        logger.info({'msg': f'Sleep for {seconds_to_sleep} seconds before sending extra data.'})
        sleep(seconds_to_sleep)

        latest_blockstamp = self._get_latest_blockstamp()
        if not self.can_submit_extra_data(latest_blockstamp):
            logger.info({'msg': 'Extra data can not be submitted.'})
            return

        self._submit_extra_data(blockstamp)

    def _submit_extra_data(self, blockstamp: ReferenceBlockStamp) -> None:
        extra_data = self.get_extra_data(blockstamp)

        if extra_data.format == FormatList.EXTRA_DATA_FORMAT_LIST_EMPTY.value:
            tx = self.report_contract.submit_report_extra_data_empty()
            self.w3.transaction.check_and_send_transaction(tx, variables.ACCOUNT)
        else:
            for tx_data in extra_data.extra_data_list:
                tx = self.report_contract.submit_report_extra_data_list(tx_data)
                self.w3.transaction.check_and_send_transaction(tx, variables.ACCOUNT)

    @lru_cache(maxsize=1)
    @duration_meter()
    def build_report(self, blockstamp: ReferenceBlockStamp) -> tuple:
        report_data = self._calculate_report(blockstamp)
        logger.info({'msg': 'Calculate report for accounting module.', 'value': report_data})
        return report_data.as_tuple()

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        # Consensus module: if contract got report data (second phase)
        processing_state = self._get_processing_state(blockstamp)
        logger.debug({'msg': 'Check if main data was submitted.', 'value': processing_state.main_data_submitted})
        return processing_state.main_data_submitted

    def can_submit_extra_data(self, blockstamp: BlockStamp) -> bool:
        """Check if Oracle can submit extra data. Can only be submitted after second phase."""
        processing_state = self._get_processing_state(blockstamp)
        return processing_state.main_data_submitted and not processing_state.extra_data_submitted

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        # Consensus module: if contract can accept the report (in any phase)
        is_reportable = not self.is_main_data_submitted(blockstamp) or self.can_submit_extra_data(blockstamp)
        logger.info({'msg': 'Check if contract could accept report.', 'value': is_reportable})
        return is_reportable

    def is_reporting_allowed(self, blockstamp: ReferenceBlockStamp) -> bool:
        if not self._is_bunker(blockstamp):
            return True

        logger.warning({'msg': '!' * 50})
        logger.warning({'msg': f'Bunker mode is active. {ALLOW_REPORTING_IN_BUNKER_MODE=}'})
        logger.warning({'msg': '!' * 50})
        return ALLOW_REPORTING_IN_BUNKER_MODE

    def _get_processing_state(self, blockstamp: BlockStamp) -> AccountingProcessingState:
        try:
            return self.report_contract.get_processing_state(blockstamp.block_hash)
        except ContractCustomError as revert:
            if revert.data != InitialEpochIsYetToArriveRevert:
                raise revert

        frame = self.get_initial_or_current_frame(blockstamp)

        return AccountingProcessingState(
            current_frame_ref_slot=frame.ref_slot,
            processing_deadline_time=frame.report_processing_deadline_slot,
            main_data_hash=HexBytes(ZERO_HASH),
            main_data_submitted=False,
            extra_data_hash=HexBytes(ZERO_HASH),
            extra_data_format=0,
            extra_data_submitted=False,
            extra_data_items_count=0,
            extra_data_items_submitted=0,
        )

    # ---------------------------------------- Build report ----------------------------------------
    def _calculate_report(self, blockstamp: ReferenceBlockStamp):
        consensus_version = self.get_consensus_version(blockstamp)
        logger.info({'msg': 'Building the report', 'consensus_version': consensus_version})
        rebase_part = self._calculate_rebase_report(blockstamp)
        modules_part = self._get_newly_exited_validators_by_modules(blockstamp)
        wq_part = self._calculate_wq_report(blockstamp)

        extra_data_part = self._calculate_extra_data_report(blockstamp)
        report_data = self._combine_report_parts(
            consensus_version,
            blockstamp,
            rebase_part,
            modules_part,
            wq_part,
            extra_data_part,
        )
        self._update_metrics(report_data)
        return report_data

    def _get_newly_exited_validators_by_modules(
        self,
        blockstamp: ReferenceBlockStamp,
    ) -> tuple[list[StakingModuleId], list[int]]:
        """
        Calculate exited validators count in all modules.
        Exclude modules without changes from the report.
        """
        staking_modules = self.w3.lido_contracts.staking_router.get_staking_modules(blockstamp.block_hash)
        exited_validators = self.lido_validator_state_service.get_exited_lido_validators(blockstamp)

        return self.get_updated_modules_stats(staking_modules, exited_validators)

    @staticmethod
    def get_updated_modules_stats(
        staking_modules: list[StakingModule],
        exited_validators_by_no: dict[NodeOperatorGlobalIndex, int],
    ) -> tuple[list[StakingModuleId], list[int]]:
        """Returns exited validators count by node operators that should be updated."""
        module_stats: dict[StakingModuleId, int] = defaultdict(int)

        for (module_id, _), validators_exited_count in exited_validators_by_no.items():
            module_stats[module_id] += validators_exited_count

        for module in staking_modules:
            if module_stats[module.id] == module.exited_validators_count:
                del module_stats[module.id]

        return list(module_stats.keys()), list(module_stats.values())

    @lru_cache(maxsize=1)
    def _get_consensus_lido_state(self, blockstamp: ReferenceBlockStamp) -> tuple[ValidatorsCount, ValidatorsBalance]:
        lido_validators = self.w3.lido_validators.get_lido_validators(blockstamp)
        logger.info({'msg': 'Calculate Lido validators count', 'value': len(lido_validators)})

        total_lido_balance = lido_validators_state_balance = sum((validator.balance for validator in lido_validators), Gwei(0))
        logger.info({'msg': 'Calculate Lido validators state balance (in Gwei)', 'value': lido_validators_state_balance})
        return ValidatorsCount(len(lido_validators)), ValidatorsBalance(Gwei(total_lido_balance))

    def _get_finalization_data(self, blockstamp: ReferenceBlockStamp) -> tuple[FinalizationShareRate, FinalizationBatches]:
        simulation = self.simulate_full_rebase(blockstamp)
        chain_config = self.get_chain_config(blockstamp)
        frame_config = self.get_frame_config(blockstamp)
        is_bunker = self._is_bunker(blockstamp)

        share_rate = (
            simulation.post_total_pooled_ether * SHARE_RATE_PRECISION_E27 // simulation.post_total_shares
            if simulation.post_total_shares
            else 0
        )
        logger.info({'msg': 'Calculate shares rate.', 'value': share_rate})

        withdrawal_service = Withdrawal(self.w3, blockstamp, chain_config, frame_config)
        batches = withdrawal_service.get_finalization_batches(
            is_bunker,
            share_rate,
            simulation.withdrawals,
            simulation.el_reward,
        )

        logger.info({'msg': 'Calculate last withdrawal id to finalize.', 'value': batches})

        return FinalizationShareRate(share_rate), batches

    @lru_cache(maxsize=1)
    def simulate_cl_rebase(self, blockstamp: ReferenceBlockStamp) -> LidoReportRebase:
        """
        Simulate rebase excluding any execution rewards.
        This used to check worst scenarios in bunker service.
        """
        return self.simulate_rebase_after_report(blockstamp, el_rewards=Wei(0))

    def simulate_full_rebase(self, blockstamp: ReferenceBlockStamp) -> LidoReportRebase:
        el_rewards = self.w3.lido_contracts.get_el_vault_balance(blockstamp)
        return self.simulate_rebase_after_report(blockstamp, el_rewards=el_rewards)

    def simulate_rebase_after_report(
        self,
        blockstamp: ReferenceBlockStamp,
        el_rewards: Wei,
    ) -> LidoReportRebase:
        """
        To calculate how much withdrawal request protocol can finalize - needs finalization share rate after this report
        """
        validators_count, cl_balance = self._get_consensus_lido_state(blockstamp)

        chain_conf = self.get_chain_config(blockstamp)

        return self.w3.lido_contracts.lido.handle_oracle_report(
            # Lido contract has sanity check that timestamp is not in the future.
            # That's why we get revert if timestamp in args > call block timestamp.
            # In normal case, we call handleOracleReport with timestamp == call block timestamp.
            blockstamp.block_timestamp,  # _reportTimestamp
            self._get_slots_elapsed_from_last_report(blockstamp) * chain_conf.seconds_per_slot,  # _timeElapsed
            # CL values
            validators_count,  # _clValidators
            gwei_to_wei(cl_balance),  # _clBalance
            # EL values
            self.w3.lido_contracts.get_withdrawal_balance(blockstamp),  # _withdrawalVaultBalance
            el_rewards,  # _elRewardsVaultBalance
            self.get_shares_to_burn(blockstamp),  # _sharesRequestedToBurn
            self.w3.lido_contracts.accounting_oracle.address,
            blockstamp.ref_slot,
            blockstamp.block_hash,
        )

    def get_shares_to_burn(self, blockstamp: ReferenceBlockStamp) -> int:
        shares_data = self.w3.lido_contracts.burner.get_shares_requested_to_burn(blockstamp.block_hash)
        return shares_data.cover_shares + shares_data.non_cover_shares

    def _get_slots_elapsed_from_last_report(self, blockstamp: ReferenceBlockStamp):
        chain_conf = self.get_chain_config(blockstamp)
        frame_config = self.get_frame_config(blockstamp)

        last_ref_slot = self.w3.lido_contracts.get_accounting_last_processing_ref_slot(blockstamp)

        if last_ref_slot:
            slots_elapsed = blockstamp.ref_slot - last_ref_slot
        else:
            # https://github.com/lidofinance/core/blob/master/contracts/0.8.9/oracle/HashConsensus.sol#L667
            slots_elapsed = blockstamp.ref_slot - (frame_config.initial_epoch * chain_conf.slots_per_epoch - 1)

        return slots_elapsed

    @lru_cache(maxsize=1)
    def _is_bunker(self, blockstamp: ReferenceBlockStamp) -> BunkerMode:
        frame_config = self.get_frame_config(blockstamp)
        chain_config = self.get_chain_config(blockstamp)
        cl_rebase_report = self.simulate_cl_rebase(blockstamp)

        bunker_mode = self.bunker_service.is_bunker_mode(
            blockstamp,
            frame_config,
            chain_config,
            cl_rebase_report,
        )
        logger.info({'msg': 'Calculate bunker mode.', 'value': bunker_mode})
        return BunkerMode(bunker_mode)

    @lru_cache(maxsize=1)
    def get_extra_data(self, blockstamp: ReferenceBlockStamp) -> ExtraData:
        stuck_validators, exited_validators, orl = self._get_generic_extra_data(blockstamp)

        return ExtraDataService.collect(
            stuck_validators,
            exited_validators,
            orl.max_items_per_extra_data_transaction,
            orl.max_node_operators_per_extra_data_item,
        )

    @lru_cache(maxsize=1)
    def _get_generic_extra_data(self, blockstamp: ReferenceBlockStamp) -> GenericExtraData:
        chain_config = self.get_chain_config(blockstamp)
        stuck_validators = self.lido_validator_state_service.get_lido_newly_stuck_validators(blockstamp, chain_config)
        logger.info({'msg': 'Calculate stuck validators.', 'value': stuck_validators})
        exited_validators = self.lido_validator_state_service.get_lido_newly_exited_validators(blockstamp)
        logger.info({'msg': 'Calculate exited validators.', 'value': exited_validators})
        orl = self.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits(blockstamp.block_hash)
        return stuck_validators, exited_validators, orl

    # fetches validators_count, cl_balance, withdrawal_balance, el_vault_balance, shares_to_burn
    def _calculate_rebase_report(self, blockstamp: ReferenceBlockStamp) -> RebaseReport:
        validators_count, cl_balance = self._get_consensus_lido_state(blockstamp)
        withdrawal_vault_balance = self.w3.lido_contracts.get_withdrawal_balance(blockstamp)
        el_rewards_vault_balance = self.w3.lido_contracts.get_el_vault_balance(blockstamp)
        shares_requested_to_burn = self.get_shares_to_burn(blockstamp)
        return validators_count, cl_balance, withdrawal_vault_balance, el_rewards_vault_balance, shares_requested_to_burn

    # calculates is_bunker, finalization_share_rate, finalization_batches
    def _calculate_wq_report(self, blockstamp: ReferenceBlockStamp) -> WqReport:
        is_bunker = self._is_bunker(blockstamp)
        finalization_share_rate, finalization_batches = self._get_finalization_data(blockstamp)
        return is_bunker, finalization_share_rate, finalization_batches

    def _calculate_extra_data_report(self, blockstamp: ReferenceBlockStamp) -> ExtraData:
        stuck_validators, exited_validators, orl = self._get_generic_extra_data(blockstamp)
        return ExtraDataService.collect(
            stuck_validators,
            exited_validators,
            orl.max_items_per_extra_data_transaction,
            orl.max_node_operators_per_extra_data_item,
        )

    @staticmethod
    def _update_metrics(report_data: ReportData):
        ACCOUNTING_IS_BUNKER.set(report_data.is_bunker)
        ACCOUNTING_CL_BALANCE_GWEI.set(report_data.cl_balance_gwei)
        ACCOUNTING_EL_REWARDS_VAULT_BALANCE_WEI.set(report_data.el_rewards_vault_balance)
        ACCOUNTING_WITHDRAWAL_VAULT_BALANCE_WEI.set(report_data.withdrawal_vault_balance)

    @staticmethod
    def _combine_report_parts(
        consensus_version: int,
        blockstamp: ReferenceBlockStamp,
        report_rebase_part: RebaseReport,
        report_modules_part: tuple[list[StakingModuleId], list[int]],
        report_wq_part: WqReport,
        extra_data: ExtraData
    ) -> ReportData:
        validators_count, cl_balance, withdrawal_vault_balance, el_rewards_vault_balance, shares_requested_to_burn = report_rebase_part
        staking_module_ids_list, exit_validators_count_list = report_modules_part
        is_bunker, finalization_share_rate, finalization_batches = report_wq_part
        return ReportData(
            consensus_version=consensus_version,
            ref_slot=blockstamp.ref_slot,
            validators_count=validators_count,
            cl_balance_gwei=cl_balance,
            staking_module_ids_with_exited_validators=staking_module_ids_list,
            count_exited_validators_by_staking_module=exit_validators_count_list,
            withdrawal_vault_balance=withdrawal_vault_balance,
            el_rewards_vault_balance=el_rewards_vault_balance,
            shares_requested_to_burn=shares_requested_to_burn,
            withdrawal_finalization_batches=finalization_batches,
            finalization_share_rate=finalization_share_rate,
            is_bunker=is_bunker,
            extra_data_format=extra_data.format,
            extra_data_hash=extra_data.data_hash,
            extra_data_items_count=extra_data.items_count,
        )
