import logging
from collections import defaultdict
from time import sleep

from hexbytes import HexBytes
from web3.exceptions import ContractCustomError
from web3.types import Wei

from src import variables
from src.constants import SHARE_RATE_PRECISION_E27
from src.metrics.prometheus.accounting import (
    ACCOUNTING_BALANCE_GWEI,
    ACCOUNTING_IS_BUNKER,
    VAULTS_TOTAL_VALUE,
)
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.common.types import ZERO_HASH, ModuleExecuteDelay
from src.modules.oracles.accounting.third_phase.extra_data import ExtraDataService
from src.modules.oracles.accounting.third_phase.types import ExtraData, FormatList
from src.modules.oracles.accounting.types import (
    AccountingProcessingState,
    BunkerMode,
    FinalizationShareRate,
    ReportData,
    ReportSimulationPayload,
    ReportSimulationResults,
    Shares,
    VaultsReport,
    VaultsTreeCid,
    VaultsTreeRoot,
)
from src.modules.oracles.common.consensus import (
    InitialEpochIsYetToArriveRevert,
)
from src.modules.oracles.common.oracle_module import OracleModule
from src.providers.execution.contracts.accounting_oracle import AccountingOracleContract
from src.services.bunker import BunkerService
from src.services.staking_vaults import StakingVaultsService
from src.services.validator_state import LidoValidatorStateService
from src.services.withdrawal import Withdrawal
from src.types import (
    BlockStamp,
    FinalizationBatches,
    Gwei,
    ReferenceBlockStamp,
    StakingModuleId,
)
from src.utils.apr import calculate_gross_core_apr
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.units import gwei_to_wei
from src.variables import ALLOW_REPORTING_IN_BUNKER_MODE
from src.web3py.types import Web3


logger = logging.getLogger(__name__)


class Accounting(OracleModule[Web3]):
    """
    Accounting module updates the protocol TVL, distributes node-operator rewards,
    and processes user withdrawal requests.

    Report goes in three phases:
        - Send report hash
        - Send report data (with extra data hash inside)
            Contains information about lido state, withdrawal requests to finalize,
            and exited validators count by module.
        - Send extra data
            Contains exited validator's updates count by each node operator.
    """

    COMPATIBLE_CONTRACT_VERSION = 5
    COMPATIBLE_CONSENSUS_VERSION = 6

    def __init__(self, w3: Web3):
        self.report_contract: AccountingOracleContract = w3.lido_contracts.accounting_oracle
        super().__init__(w3)

        self.lido_validator_state_service = LidoValidatorStateService(self.w3)
        self.bunker_service = BunkerService(self.w3)
        self.staking_vaults = StakingVaultsService(self.w3)

    def refresh_contracts(self) -> None:
        """Refresh contract instances from the Web3 provider."""
        self.report_contract = self.w3.lido_contracts.accounting_oracle  # type: ignore

    def is_contracts_addresses_changed(self) -> bool:
        return self.w3.lido_contracts.has_contract_address_changed()

    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        """
        Execute the accounting module's reporting cycle.
        Includes reporting of the main data and the extra data.
        """
        report_blockstamp = self.get_blockstamp_for_report(last_finalized_blockstamp)

        if not report_blockstamp or not self._check_compatibility(report_blockstamp):
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        self.process_report(report_blockstamp)
        # Third phase of a report. Specific for accounting.
        self.process_extra_data(report_blockstamp)
        return ModuleExecuteDelay.NEXT_SLOT

    def process_extra_data(self, blockstamp: ReferenceBlockStamp) -> None:
        """
        Process the third phase of the report: submit extra data.
        The extra data can only be submitted after the main data has been submitted.
        """
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
        """Fetch and submit extra data to the accounting oracle contract."""
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
        """Check if the main report data (second phase) was already submitted for the current frame."""
        # Consensus module: if contract got report data (second phase)
        processing_state = self._get_processing_state(blockstamp)
        logger.debug({'msg': 'Check if main data was submitted.', 'value': processing_state.main_data_submitted})
        return processing_state.main_data_submitted

    def can_submit_extra_data(self, blockstamp: BlockStamp) -> bool:
        """Check if Oracle can submit extra data. Can only be submitted after second phase."""
        processing_state = self._get_processing_state(blockstamp)
        return processing_state.main_data_submitted and not processing_state.extra_data_submitted

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        """Check if the contract is in a state where it can accept report data (either phase 2 or phase 3)."""
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
                raise

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
    def _calculate_report(self, blockstamp: ReferenceBlockStamp) -> ReportData:
        """Calculate all the data required for the main oracle report."""
        consensus_version = self.get_consensus_version(blockstamp)
        logger.info({'msg': 'Building the report', 'consensus_version': consensus_version})

        cl_balance = self._get_cl_validators_balance(blockstamp)
        cl_pending_balance = self._get_cl_pending_validators_balance(blockstamp)

        exit_sm_ids_list, exit_validators_count_list = self._get_newly_exited_validators_by_modules(blockstamp)

        balance_sm_ids_list, validator_balance_by_sm = self._get_balances_by_modules(blockstamp)

        withdrawal_vault_balance = self.w3.lido_contracts.get_withdrawal_balance(blockstamp)
        el_rewards_vault_balance = self.w3.lido_contracts.get_el_vault_balance(blockstamp)
        shares_requested_to_burn = self.get_shares_to_burn(blockstamp)

        finalization_batches, finalization_share_rate = self._get_finalization_data(blockstamp)
        is_bunker = self._is_bunker(blockstamp)

        tree_root, tree_cid = self._handle_vaults_report(blockstamp)
        extra_data = self.get_extra_data(blockstamp)

        report_data = ReportData(
            consensus_version=consensus_version,
            ref_slot=blockstamp.ref_slot,
            cl_validators_balance_gwei=cl_balance,
            cl_pending_balance_gwei=cl_pending_balance,
            staking_module_ids_with_exited_validators=exit_sm_ids_list,
            count_exited_validators_by_staking_module=exit_validators_count_list,
            staking_module_ids_with_updated_balance=balance_sm_ids_list,
            validator_balances_gwei_by_staking_module=validator_balance_by_sm,
            withdrawal_vault_balance=withdrawal_vault_balance,
            el_rewards_vault_balance=el_rewards_vault_balance,
            shares_requested_to_burn=shares_requested_to_burn,
            withdrawal_finalization_batches=finalization_batches,
            finalization_share_rate=finalization_share_rate,
            is_bunker=is_bunker,
            vaults_tree_root=tree_root,
            vaults_tree_cid=tree_cid,
            extra_data_format=extra_data.format,
            extra_data_hash=extra_data.data_hash,
            extra_data_items_count=extra_data.items_count,
        )

        self._update_metrics(report_data)
        return report_data

    def _get_cl_validators_balance(self, blockstamp: ReferenceBlockStamp) -> Gwei:
        lido_validators = self.w3.lido_validators.get_active_lido_validators(blockstamp)
        logger.info({'msg': 'Get lido validators.', 'value': len(lido_validators)})

        validator_balance_sum = Gwei(sum(validator.balance for validator in lido_validators))
        logger.info({'msg': 'Calculate active balance.', 'value': validator_balance_sum})

        return validator_balance_sum

    def _get_cl_pending_validators_balance(self, blockstamp: ReferenceBlockStamp) -> Gwei:
        """Calculate the total pending balance on the Consensus Layer.

        Includes both new validators awaiting activation and pending top-up deposits for
        existing active validators. Top-ups must be included because they are not yet reflected
        in validator.balance on the CL; if they remain unprocessed across a frame boundary,
        they would otherwise be invisible to the contract's accounting (absent from both
        clPendingBalanceAtLastReport and depositedForCurrentReport).
        """
        lido_pending_balance_by_keys = self.w3.lido_validators.get_pending_lido_validators(blockstamp)
        new_validators_pending = Gwei(
            sum(pending.amount for _, pendings in lido_pending_balance_by_keys.values() for pending in pendings)
        )
        active_validators = self.w3.lido_validators.get_active_lido_validators(blockstamp)
        topups_pending = Gwei(
            sum(topup.amount for v in active_validators for topup in v.pending_topups)
        )
        return Gwei(new_validators_pending + topups_pending)

    def _get_newly_exited_validators_by_modules(
        self,
        blockstamp: ReferenceBlockStamp,
    ) -> tuple[list[StakingModuleId], list[int]]:
        """
        Calculate exited validators count in all modules.
        Exclude modules without changes from the report.
        """
        exited_validators = self.lido_validator_state_service.get_exited_lido_validators(blockstamp)
        module_stats: dict[StakingModuleId, int] = defaultdict(int)
        for (module_id, _), validators_exited_count in exited_validators.items():
            module_stats[module_id] += validators_exited_count

        staking_modules = self.w3.lido_contracts.staking_router.get_staking_modules(blockstamp.block_hash)
        for module in staking_modules:
            if module_stats[module.id] == module.exited_validators_count:
                del module_stats[module.id]

        items = sorted(module_stats.items(), key=lambda item: item[0])
        return [sm_id for sm_id, _ in items], [val_exits for _, val_exits in items]

    def _get_balances_by_modules(self, blockstamp: ReferenceBlockStamp) -> tuple[list[StakingModuleId], list[Gwei]]:
        """
        Calculate active balances by modules.
        Balances are aggregated for all modules returned by `_get_no_active_balance`.
        """
        sm_by_address = self.w3.lido_contracts.staking_router.get_staking_modules_by_address(blockstamp.block_hash)
        module_stats: dict[StakingModuleId, Gwei] = {
            sm_by_address[module.staking_module_address].id: Gwei(0) for module in sm_by_address.values()
        }

        validators_by_no = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)
        for (module_id, _), validators in validators_by_no.items():
            for validator in validators:
                module_stats[module_id] += validator.balance

        items = sorted(module_stats.items(), key=lambda item: item[0])
        return (
            [sm_id for sm_id, _ in items],
            [balance for _, balance in items],
        )

    def get_shares_to_burn(self, blockstamp: ReferenceBlockStamp) -> Shares:
        """Calculate the total number of shares requested to be burned (cover and non-cover)."""
        shares_data = self.w3.lido_contracts.burner.get_shares_requested_to_burn(blockstamp.block_hash)
        return Shares(shares_data.cover_shares + shares_data.non_cover_shares)

    def _get_finalization_data(
        self, blockstamp: ReferenceBlockStamp
    ) -> tuple[FinalizationBatches, FinalizationShareRate]:
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
            simulation.withdrawals_vault_transfer,
            simulation.el_rewards_vault_transfer,
        )

        logger.info({'msg': 'Calculate last withdrawal id to finalize.', 'value': batches})

        return batches, FinalizationShareRate(share_rate)

    def simulate_full_rebase(self, blockstamp: ReferenceBlockStamp) -> ReportSimulationResults:
        """Simulate a full oracle report rebase, including execution layer rewards."""
        el_rewards = self.w3.lido_contracts.get_el_vault_balance(blockstamp)
        return self.simulate_rebase_after_report(blockstamp, el_rewards=el_rewards)

    @lru_cache(maxsize=1)
    def simulate_cl_rebase(self, blockstamp: ReferenceBlockStamp) -> ReportSimulationResults:
        """
        Simulate rebase excluding any execution rewards.
        This used to check the worst scenarios in bunker service.
        """
        return self.simulate_rebase_after_report(blockstamp, el_rewards=Wei(0))

    def simulate_rebase_after_report(
        self,
        blockstamp: ReferenceBlockStamp,
        el_rewards: Wei,
    ) -> ReportSimulationResults:
        """
        To calculate how much withdrawal request protocol can finalize - needs finalization share rate after this report
        """
        chain_conf = self.get_chain_config(blockstamp)
        cl_balance = self._get_cl_validators_balance(blockstamp)
        pending_balance = self._get_cl_pending_validators_balance(blockstamp)

        report = ReportSimulationPayload(
            timestamp=blockstamp.block_timestamp,
            time_elapsed=self._get_slots_elapsed_from_last_report(blockstamp) * chain_conf.seconds_per_slot,
            cl_validators_balance=gwei_to_wei(cl_balance),
            cl_pending_balance=gwei_to_wei(pending_balance),
            withdrawal_vault_balance=self.w3.lido_contracts.get_withdrawal_balance(blockstamp),
            el_rewards_vault_balance=el_rewards,
            shares_requested_to_burn=self.get_shares_to_burn(blockstamp),
            withdrawal_finalization_batches=[],  # For simulation, we assume no withdrawals
            simulated_share_rate=0,  # For simulation, we assume 0 share rate
        )

        return self.w3.lido_contracts.accounting.simulate_oracle_report(
            report,
            blockstamp.block_hash,
        )

    def _get_slots_elapsed_from_last_report(self, blockstamp: ReferenceBlockStamp) -> int:
        """Calculate the number of slots passed since the last successful oracle report."""
        chain_conf = self.get_chain_config(blockstamp)
        frame_config = self.get_frame_config(blockstamp)

        last_ref_slot = self.w3.lido_contracts.get_accounting_last_processing_ref_slot(blockstamp)

        if last_ref_slot:
            slots_elapsed = blockstamp.ref_slot - last_ref_slot
        else:
            # https://github.com/lidofinance/core/blob/master/contracts/0.8.9/oracle/HashConsensus.sol#L667
            prev_slot = max(
                (frame_config.initial_epoch - frame_config.epochs_per_frame) * chain_conf.slots_per_epoch - 1,
                0,
            )
            slots_elapsed = blockstamp.ref_slot - prev_slot

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
        """Collect and encode extra data (newly exited validators by node operator)."""
        exited_validators = self.lido_validator_state_service.get_lido_newly_exited_validators(blockstamp)
        logger.info({'msg': 'Calculate exited validators.', 'value': exited_validators})

        orl = self.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits(blockstamp.block_hash)

        return ExtraDataService.collect(
            exited_validators,
            orl.max_items_per_extra_data_transaction,
            orl.max_node_operators_per_extra_data_item,
        )

    def _handle_vaults_report(self, blockstamp: ReferenceBlockStamp) -> VaultsReport:
        """
        Generates and publishes a Merkle tree report for staking vaults at a given blockstamp.

        This function performs the following steps:
        1. Fetches staking vaults at the given block number.
        2. If no vaults are found, returns empty report data.
        3. Retrieves validator data and pending deposits at the refBlock.
        4. Loads chain configuration for the target block.
        5. Computes total values for all vaults, including validator balances and pending deposits.
        6. Calculates vault-specific fees and slashing reserves.
        7. Constructs structured tree data combining vault values, fees, and slashing reserves.
        8. Builds a Merkle tree from this data.
        9. Publishes the Merkle tree to IPFS (or similar) and retrieves a content ID (CID).
        10. Returns the Merkle tree root and the CID as the vaults report.

        Args:
            blockstamp (ReferenceBlockStamp): Block context used to fetch vault and validator data.

        Returns:
            VaultsReport: A tuple containing the Merkle tree root (as `bytes`) and the CID (as `str`)
                          identifying the published tree data.
        """

        vaults = self.staking_vaults.get_vaults(blockstamp.block_hash)
        if not vaults:
            return VaultsTreeRoot(ZERO_HASH), VaultsTreeCid('')

        current_frame = self.get_frame_number_by_slot(blockstamp)
        validators = self.w3.cc.get_validators(blockstamp)
        pending_deposits = self.w3.cc.get_pending_deposits(blockstamp)
        chain_config = self.get_chain_config(blockstamp)
        frame_config = self.get_frame_config(blockstamp)
        simulation = self.simulate_full_rebase(blockstamp)

        vaults_total_values = self.staking_vaults.get_vaults_total_values(
            vaults=vaults,
            validators=validators,
            pending_deposits=pending_deposits,
            block_identifier=blockstamp.block_hash,
        )

        slots_elapsed = self._get_slots_elapsed_from_last_report(blockstamp)

        core_apr_ratio = calculate_gross_core_apr(
            pre_total_ether=simulation.pre_total_pooled_ether,
            pre_total_shares=simulation.pre_total_shares,
            post_internal_ether=simulation.post_internal_ether,
            post_internal_shares=simulation.post_internal_shares,
            shares_minted_as_fees=simulation.shares_to_mint_as_fees,
            time_elapsed_seconds=slots_elapsed * chain_config.seconds_per_slot,
        )

        latest_onchain_ipfs_report_data = self.staking_vaults.get_latest_onchain_ipfs_report_data(blockstamp.block_hash)
        vaults_fees = self.staking_vaults.get_vaults_fees(
            blockstamp=blockstamp,
            vaults=vaults,
            vaults_total_values=vaults_total_values,
            latest_onchain_ipfs_report_data=latest_onchain_ipfs_report_data,
            core_apr_ratio=core_apr_ratio,
            pre_total_pooled_ether=simulation.pre_total_pooled_ether,
            pre_total_shares=simulation.pre_total_shares,
            frame_config=frame_config,
            chain_config=chain_config,
            current_frame=current_frame,
        )
        vaults_slashing_reserve = self.staking_vaults.get_vaults_slashing_reserve(
            bs=blockstamp, vaults=vaults, validators=validators, chain_config=chain_config
        )
        tree_data = self.staking_vaults.build_tree_data(
            vaults=vaults,
            vaults_total_values=vaults_total_values,
            vaults_fees=vaults_fees,
            vaults_slashing_reserve=vaults_slashing_reserve,
        )

        merkle_tree = self.staking_vaults.get_merkle_tree(tree_data)
        tree_cid = self.staking_vaults.publish_tree(
            bs=blockstamp,
            tree=merkle_tree,
            vaults=vaults,
            prev_tree_cid=latest_onchain_ipfs_report_data.report_cid,
            chain_config=chain_config,
            vaults_fee_map=vaults_fees,
        )

        VAULTS_TOTAL_VALUE.set(sum(vaults_total_values.values()))
        logger.info({'msg': "Tree's proof ipfs", 'ipfs': str(tree_cid), 'treeHex': f"0x{merkle_tree.root.hex()}"})

        return VaultsTreeRoot(merkle_tree.root), VaultsTreeCid(str(tree_cid))

    @staticmethod
    def _update_metrics(report_data: ReportData):
        ACCOUNTING_IS_BUNKER.set(report_data.is_bunker)
        ACCOUNTING_BALANCE_GWEI.labels('pending').set(report_data.cl_pending_balance_gwei)
        ACCOUNTING_BALANCE_GWEI.labels('active').set(report_data.cl_validators_balance_gwei)
        ACCOUNTING_BALANCE_GWEI.labels('withdrawal_vault').set(report_data.withdrawal_vault_balance * 10**9)
        ACCOUNTING_BALANCE_GWEI.labels('el_reward_vault').set(report_data.el_rewards_vault_balance * 10**9)
