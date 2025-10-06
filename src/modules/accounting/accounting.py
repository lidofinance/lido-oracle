import logging
from collections import defaultdict
from time import sleep

from hexbytes import HexBytes
from web3.exceptions import ContractCustomError
from web3.types import Wei

from src import variables
from src.constants import SHARE_RATE_PRECISION_E27
from src.metrics.prometheus.accounting import (
    ACCOUNTING_CL_BALANCE_GWEI,
    ACCOUNTING_EL_REWARDS_VAULT_BALANCE_WEI,
    ACCOUNTING_IS_BUNKER,
    ACCOUNTING_WITHDRAWAL_VAULT_BALANCE_WEI,
    VAULTS_TOTAL_VALUE,
)
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.accounting.third_phase.extra_data import ExtraDataService
from src.modules.accounting.third_phase.types import ExtraData, FormatList
from src.modules.accounting.types import (
    AccountingProcessingState,
    BunkerMode,
    FinalizationShareRate,
    GenericExtraData,
    RebaseReport,
    ReportData,
    ReportSimulationPayload,
    ReportSimulationResults,
    ValidatorsBalance,
    ValidatorsCount,
    VaultsReport,
    WqReport,
)
from src.modules.submodules.consensus import (
    ConsensusModule,
    InitialEpochIsYetToArriveRevert,
)
from src.modules.submodules.oracle_module import BaseModule, ModuleExecuteDelay
from src.modules.submodules.types import ZERO_HASH
from src.providers.consensus.types import PendingDeposit
from src.providers.execution.contracts.accounting_oracle import AccountingOracleContract
from src.services.bunker import BunkerService
from src.services.staking_vaults import StakingVaultsService
from src.services.validator_state import LidoValidatorStateService
from src.services.withdrawal import Withdrawal
from src.types import (
    BlockStamp,
    FinalizationBatches,
    Gwei,
    NodeOperatorGlobalIndex,
    ReferenceBlockStamp,
    StakingModuleId,
)
from src.utils.apr import calculate_gross_core_apr
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.deposit_signature import is_valid_deposit_signature
from src.utils.types import hex_str_to_bytes
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
            Contains exited validator's updates count by each node operator.
    """

    COMPATIBLE_CONTRACT_VERSION = 3
    COMPATIBLE_CONSENSUS_VERSION = 5

    def __init__(self, w3: Web3):
        self.report_contract: AccountingOracleContract = w3.lido_contracts.accounting_oracle
        super().__init__(w3)

        self.lido_validator_state_service = LidoValidatorStateService(self.w3)
        self.bunker_service = BunkerService(self.w3)
        self.staking_vaults = StakingVaultsService(self.w3)

    def refresh_contracts(self):
        self.report_contract = self.w3.lido_contracts.accounting_oracle  # type: ignore

    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        report_blockstamp = self.get_blockstamp_for_report(last_finalized_blockstamp)

        if not report_blockstamp or not self._check_compatability(report_blockstamp):
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
        modules_balance_part = self._get_modules_balances(blockstamp)
        pending_deposits_balance = self._calculate_pending_deposits_balance(blockstamp)
        wq_part = self._calculate_wq_report(blockstamp)

        vaults_part = self._handle_vaults_report(blockstamp)

        extra_data_part = self._calculate_extra_data_report(blockstamp)
        report_data = self._combine_report_parts(
            consensus_version,
            blockstamp,
            rebase_part,
            modules_part,
            modules_balance_part,
            pending_deposits_balance,
            wq_part,
            vaults_part,
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
        logger.info({
            'msg': 'Calculate Lido validators state balance (in Gwei)',
            'value': lido_validators_state_balance,
        })

        return ValidatorsCount(len(lido_validators)), ValidatorsBalance(Gwei(total_lido_balance))

    @lru_cache(maxsize=1)
    def _calculate_pending_deposits_balance(self, blockstamp: ReferenceBlockStamp) -> Gwei:
        """
        Calculate total pending deposits balance for Lido validators that are not yet active.

        Algorithm (based on pending_deposits_integration_report.md):
        1. Get all pending deposits from consensus layer
        2. Get all active Lido validators
        3. Get Lido withdrawal credentials
        4. For each pending deposit pubkey:
           - Skip if validator with this pubkey already exists
           - Validate deposits with BLS signature verification and withdrawal credentials matching
           - Sum up valid deposits
        """
        pending_deposits = self.w3.cc.get_pending_deposits(blockstamp)

        if not pending_deposits:
            logger.info({'msg': 'No pending deposits found'})
            return Gwei(0)

        # Get Lido withdrawal credentials
        lido_wc = self.w3.lido_contracts.lido.get_withdrawal_credentials(blockstamp.block_hash)

        # Get all active Lido validators
        lido_validators = self.w3.lido_validators.get_lido_validators(blockstamp)
        lido_validator_pubkeys = set(validator.validator.pubkey for validator in lido_validators)

        # Group deposits by pubkey
        deposits_by_pubkey = defaultdict(list)
        for deposit in pending_deposits:
            deposits_by_pubkey[deposit.pubkey].append(deposit)

        total_pending_balance = Gwei(0)
        validated_pubkeys_count = 0

        # Process each pubkey's deposits
        for pubkey, deposits in deposits_by_pubkey.items():
            # Skip if validator already exists
            if pubkey in lido_validator_pubkeys:
                continue

            # Validate and sum deposits for this pubkey
            valid_balance = self._get_valid_lido_deposits_value(
                lido_withdrawal_credentials=lido_wc,
                pubkey_deposits=deposits,
            )

            if valid_balance > 0:
                total_pending_balance = Gwei(total_pending_balance + valid_balance)
                validated_pubkeys_count += 1

        logger.info({
            'msg': 'Calculate pending deposits balance (in Gwei)',
            'value': total_pending_balance,
            'total_deposits': len(pending_deposits),
            'new_validators_with_deposits': validated_pubkeys_count,
        })

        return total_pending_balance

    def _get_valid_lido_deposits_value(
        self,
        lido_withdrawal_credentials: str,
        pubkey_deposits: list[PendingDeposit],
    ) -> Gwei:
        """
        Validates pending deposits for a single pubkey according to pending_deposits_integration_report.md.

        CRITICAL LOGIC from original _get_valid_deposits_value():
        - Once a valid deposit is found (BLS signature + WC check), all subsequent deposits are accepted WITHOUT checks
        - This protects against front-run attacks (attacker can't create valid BLS signature without private key)
        - Uses "all-or-nothing" logic: if first valid deposit has wrong WC → return 0

        Algorithm:
        1. For each deposit in order:
           a. If already found valid deposit → accept without checks (front-run protection)
           b. Otherwise check BLS signature
           c. If valid → check withdrawal_credentials match
           d. If WC mismatch on first valid → return 0 (all-or-nothing)
           e. If WC match → mark as valid_found and continue
        """
        if not pubkey_deposits:
            return Gwei(0)

        valid_deposits_value = Gwei(0)
        valid_found = False
        genesis_config = self.get_cc_genesis_config()
        genesis_fork_version = genesis_config.genesis_fork_version
        genesis_validators_root = genesis_config.genesis_validators_root

        for deposit in pubkey_deposits:
            # CRITICAL: If already found valid deposit - accept ALL subsequent ones WITHOUT checks
            if valid_found:
                valid_deposits_value = Gwei(valid_deposits_value + deposit.amount)
                continue

            # Check BLS signature
            is_valid = is_valid_deposit_signature(
                pubkey=hex_str_to_bytes(deposit.pubkey),
                withdrawal_credentials=hex_str_to_bytes(deposit.withdrawal_credentials),
                amount_gwei=deposit.amount,
                signature=hex_str_to_bytes(deposit.signature),
                genesis_validators_root=bytes.fromhex(genesis_validators_root),
                fork_version=bytes.fromhex(genesis_fork_version),
            )

            if not is_valid:
                logger.warning({
                    'msg': f'Invalid deposit signature for deposit: {deposit.signature}.',
                })
                continue

            # Check withdrawal_credentials match
            if deposit.withdrawal_credentials != lido_withdrawal_credentials:
                logger.warning({
                    'msg': (
                        f"Mismatch deposit withdrawal_credentials {deposit.withdrawal_credentials} "
                        f"to Lido protocol withdrawal_credentials {lido_withdrawal_credentials}. "
                        f"Skipping any further pending deposits count."
                    )
                })
                # CRITICAL: If first VALID deposit has wrong WC → return 0 (all-or-nothing)
                return Gwei(0)

            # Found valid deposit - mark and include
            valid_found = True
            valid_deposits_value = Gwei(valid_deposits_value + deposit.amount)

        return valid_deposits_value

    @lru_cache(maxsize=1)
    def _get_modules_balances(
        self, blockstamp: ReferenceBlockStamp
    ) -> tuple[list[StakingModuleId], list[Gwei], list[Gwei]]:
        """
        Calculate active and pending balances for each staking module.

        Returns:
            tuple of:
            - list of staking module IDs with updated balances
            - list of active balances (in Gwei) for corresponding modules
            - list of pending balances (in Gwei) for corresponding modules
        """
        staking_modules = self.w3.lido_contracts.staking_router.get_staking_modules(blockstamp.block_hash)
        lido_validators = self.w3.lido_validators.get_lido_validators(blockstamp)

        pending_deposits = self.w3.cc.get_pending_deposits(blockstamp)
        pending_balances_by_pubkey = self.staking_vaults.get_total_pending_amount_by_pubkey(pending_deposits)

        # Build module address to module ID mapping
        module_address_to_id: dict[str, StakingModuleId] = {}
        for module in staking_modules:
            module_address_to_id[module.staking_module_address] = module.id

        # Calculate balances per module
        module_active_balances: dict[StakingModuleId, Gwei] = defaultdict(lambda: Gwei(0))
        module_pending_balances: dict[StakingModuleId, Gwei] = defaultdict(lambda: Gwei(0))

        # Sum active balances from validators
        for validator in lido_validators:
            module_address = validator.lido_id.moduleAddress
            if module_id := module_address_to_id.get(module_address):
                module_active_balances[module_id] = Gwei(
                    module_active_balances[module_id] + validator.balance
                )

        # Sum pending balances from pending deposits
        lido_validator_pubkeys = set(validator.validator.pubkey for validator in lido_validators)
        lido_keys = self.w3.kac.get_used_lido_keys(blockstamp)

        # Build pubkey to module address mapping
        pubkey_to_module_address = {key.key: key.moduleAddress for key in lido_keys}

        for pubkey, pb in pending_balances_by_pubkey.items():
            # Only count pending deposits for validators that don't exist yet
            if pubkey not in lido_validator_pubkeys:
                if module_address := pubkey_to_module_address.get(pubkey):
                    if module_id := module_address_to_id.get(module_address):
                        module_pending_balances[module_id] = Gwei(
                            module_pending_balances[module_id] + pb
                        )

        # Prepare result lists (only modules with any balance)
        module_ids: list[StakingModuleId] = []
        active_balances: list[Gwei] = []
        pending_balances: list[Gwei] = []

        all_module_ids = set(module_active_balances.keys()) | set(module_pending_balances.keys())

        for module_id in sorted(all_module_ids):
            module_ids.append(module_id)
            active_balances.append(module_active_balances[module_id])
            pending_balances.append(module_pending_balances[module_id])

        logger.info({
            'msg': 'Calculate balances by staking modules',
            'modules_count': len(module_ids),
            'module_ids': module_ids,
            'active_balances': active_balances,
            'pending_balances': pending_balances,
        })

        return module_ids, active_balances, pending_balances

    def _get_finalization_data(self, blockstamp: ReferenceBlockStamp) -> tuple[FinalizationBatches, FinalizationShareRate]:
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

    @lru_cache(maxsize=1)
    def simulate_cl_rebase(self, blockstamp: ReferenceBlockStamp) -> ReportSimulationResults:
        """
        Simulate rebase excluding any execution rewards.
        This used to check worst scenarios in bunker service.
        """
        return self.simulate_rebase_after_report(blockstamp, el_rewards=Wei(0))

    def simulate_full_rebase(self, blockstamp: ReferenceBlockStamp) -> ReportSimulationResults:
        el_rewards = self.w3.lido_contracts.get_el_vault_balance(blockstamp)
        return self.simulate_rebase_after_report(blockstamp, el_rewards=el_rewards)

    def simulate_rebase_after_report(
        self,
        blockstamp: ReferenceBlockStamp,
        el_rewards: Wei,
    ) -> ReportSimulationResults:
        """
        To calculate how much withdrawal request protocol can finalize - needs finalization share rate after this report
        """
        cl_validators_count, cl_balance = self._get_consensus_lido_state(blockstamp)
        chain_conf = self.get_chain_config(blockstamp)

        simulated_share_rate = 0  # For simulation we assume 0 share rate
        withdrawal_finalization_batches: list[int] = []  # For simulation, we assume no withdrawals

        report = ReportSimulationPayload(
            timestamp=blockstamp.block_timestamp,
            time_elapsed=self._get_slots_elapsed_from_last_report(blockstamp) * chain_conf.seconds_per_slot,
            cl_validators=cl_validators_count,
            cl_balance=gwei_to_wei(cl_balance),
            withdrawal_vault_balance=self.w3.lido_contracts.get_withdrawal_balance(blockstamp),
            el_rewards_vault_balance=el_rewards,
            shares_requested_to_burn=self.get_shares_to_burn(blockstamp),
            withdrawal_finalization_batches=withdrawal_finalization_batches,
            simulated_share_rate=simulated_share_rate,
        )

        return self.w3.lido_contracts.accounting.simulate_oracle_report(
            report,
            blockstamp.block_hash,
        )

    def get_shares_to_burn(self, blockstamp: ReferenceBlockStamp) -> int:
        shares_data = self.w3.lido_contracts.burner.get_shares_requested_to_burn(blockstamp.block_hash)
        return shares_data.cover_shares + shares_data.non_cover_shares

    def _get_slots_elapsed_from_last_report(self, blockstamp: ReferenceBlockStamp) -> int:
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
        exited_validators, orl = self._get_generic_extra_data(blockstamp)

        return ExtraDataService.collect(
            exited_validators,
            orl.max_items_per_extra_data_transaction,
            orl.max_node_operators_per_extra_data_item,
        )

    @lru_cache(maxsize=1)
    def _get_generic_extra_data(self, blockstamp: ReferenceBlockStamp) -> GenericExtraData:
        exited_validators = self.lido_validator_state_service.get_lido_newly_exited_validators(blockstamp)
        logger.info({'msg': 'Calculate exited validators.', 'value': exited_validators})
        orl = self.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits(blockstamp.block_hash)
        return exited_validators, orl

    # fetches validators_count, cl_balance, withdrawal_balance, el_vault_balance, shares_to_burn
    def _calculate_rebase_report(self, blockstamp: ReferenceBlockStamp) -> RebaseReport:
        validators_count, cl_balance = self._get_consensus_lido_state(blockstamp)
        withdrawal_vault_balance = self.w3.lido_contracts.get_withdrawal_balance(blockstamp)
        el_rewards_vault_balance = self.w3.lido_contracts.get_el_vault_balance(blockstamp)
        shares_requested_to_burn = self.get_shares_to_burn(blockstamp)
        return (
            validators_count,
            cl_balance,
            withdrawal_vault_balance,
            el_rewards_vault_balance,
            shares_requested_to_burn,
        )

    # calculates is_bunker, finalization_batches
    def _calculate_wq_report(self, blockstamp: ReferenceBlockStamp) -> WqReport:
        is_bunker = self._is_bunker(blockstamp)
        finalization_batches, finalization_share_rate = self._get_finalization_data(blockstamp)
        return is_bunker, finalization_batches, finalization_share_rate

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
        if len(vaults) == 0:
            return ZERO_HASH, ''

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
            block_identifier=blockstamp.block_hash
        )

        core_apr_ratio = calculate_gross_core_apr(
            pre_total_ether=simulation.pre_total_pooled_ether,
            pre_total_shares=simulation.pre_total_shares,
            post_internal_ether=simulation.post_internal_ether,
            post_internal_shares=simulation.post_internal_shares,
            shares_minted_as_fees=simulation.shares_to_mint_as_fees,
            time_elapsed_seconds=self._get_time_elapsed_seconds_from_prev_report(blockstamp),
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

        return merkle_tree.root, str(tree_cid)

    def _calculate_extra_data_report(self, blockstamp: ReferenceBlockStamp) -> ExtraData:
        exited_validators, orl = self._get_generic_extra_data(blockstamp)
        return ExtraDataService.collect(
            exited_validators,
            orl.max_items_per_extra_data_transaction,
            orl.max_node_operators_per_extra_data_item,
        )

    @staticmethod
    def _update_metrics(report_data: ReportData):
        ACCOUNTING_IS_BUNKER.set(report_data.is_bunker)
        ACCOUNTING_CL_BALANCE_GWEI.set(report_data.cl_active_balance_gwei)
        ACCOUNTING_EL_REWARDS_VAULT_BALANCE_WEI.set(report_data.el_rewards_vault_balance)
        ACCOUNTING_WITHDRAWAL_VAULT_BALANCE_WEI.set(report_data.withdrawal_vault_balance)

    @staticmethod
    def _combine_report_parts(
        consensus_version: int,
        blockstamp: ReferenceBlockStamp,
        report_rebase_part: RebaseReport,
        report_modules_part: tuple[list[StakingModuleId], list[int]],
        report_modules_balance_part: tuple[list[StakingModuleId], list[Gwei], list[Gwei]],
        report_pending_deposits: Gwei,
        report_wq_part: WqReport,
        report_vaults_part: VaultsReport,
        extra_data: ExtraData,
    ) -> ReportData:
        _, cl_balance, withdrawal_vault_balance, el_rewards_vault_balance, shares_requested_to_burn = (
            report_rebase_part
        )
        staking_module_ids_list, exit_validators_count_list = report_modules_part
        module_ids_with_updated_balance, active_balances_by_module, pending_balances_by_module = report_modules_balance_part
        is_bunker, finalization_batches, finalization_share_rate = report_wq_part
        tree_root, tree_cid = report_vaults_part

        return ReportData(
            consensus_version=consensus_version,
            ref_slot=blockstamp.ref_slot,
            cl_active_balance_gwei=cl_balance,
            cl_pending_balance_gwei=report_pending_deposits,
            staking_module_ids_with_exited_validators=staking_module_ids_list,
            count_exited_validators_by_staking_module=exit_validators_count_list,
            staking_module_ids_with_updated_balance=module_ids_with_updated_balance,
            active_balances_gwei_by_staking_module=active_balances_by_module,
            pending_balances_gwei_by_staking_module=pending_balances_by_module,
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

    def _get_time_elapsed_seconds_from_prev_report(self, blockstamp: ReferenceBlockStamp) -> int:
        slots_elapsed = self._get_slots_elapsed_from_last_report(blockstamp)
        chain_conf = self.get_chain_config(blockstamp)
        return slots_elapsed * chain_conf.seconds_per_slot
