import logging
from collections import defaultdict
from functools import lru_cache
from time import sleep

from web3.types import Wei

from src import variables
from src.constants import SHARE_RATE_PRECISION_E27
from src.modules.accounting.typings import ReportData, AccountingProcessingState, LidoReportRebase, \
    SharesRequestedToBurn
from src.services.validator_state import LidoValidatorStateService
from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule
from src.services.withdrawal import Withdrawal
from src.services.bunker import BunkerService
from src.typings import BlockStamp, Gwei, ReferenceBlockStamp
from src.utils.abi import named_tuple_to_dataclass
from src.web3py.typings import Web3
from src.web3py.extensions.lido_validators import StakingModule, NodeOperatorGlobalIndex, StakingModuleId


logger = logging.getLogger(__name__)


class Accounting(BaseModule, ConsensusModule):
    CONSENSUS_VERSION = 1
    CONTRACT_VERSION = 1

    def __init__(self, w3: Web3):
        self.report_contract = w3.lido_contracts.accounting_oracle
        super().__init__(w3)

        self.lido_validator_state_service = LidoValidatorStateService(self.w3)
        self.bunker_service = BunkerService(self.w3)

    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> bool:
        report_blockstamp = self.get_blockstamp_for_report(last_finalized_blockstamp)

        if not report_blockstamp:
            return True

        self.process_report(report_blockstamp)
        self.process_extra_data(report_blockstamp)
        return False

    def process_extra_data(self, blockstamp: ReferenceBlockStamp):
        latest_blockstamp = self._get_latest_blockstamp()
        if self.is_extra_data_submitted(latest_blockstamp):
            logger.info({'msg': 'Extra data was submitted.'})
            return

        chain_config = self.get_chain_config(blockstamp)
        slots_to_sleep = self._get_slot_delay_before_data_submit(blockstamp)
        seconds_to_sleep = slots_to_sleep * chain_config.seconds_per_slot
        logger.info({'msg': f'Sleep for {seconds_to_sleep} before sending extra data.'})
        sleep(seconds_to_sleep)

        self._submit_extra_data(blockstamp)

    def _submit_extra_data(self, blockstamp: ReferenceBlockStamp) -> None:
        if not variables.ACCOUNT:
            logger.info({'msg': 'Dry mode. No account provided to submit extra data.'})
            return

        extra_data = self.lido_validator_state_service.get_extra_data(blockstamp, self.get_chain_config(blockstamp))

        if extra_data.extra_data:
            tx = self.report_contract.functions.submitReportExtraDataList(extra_data.extra_data)
        else:
            tx = self.report_contract.functions.submitReportExtraDataEmpty()

        self.w3.transaction.check_and_send_transaction(tx, variables.ACCOUNT)

    # Consensus module: main build report method
    @lru_cache(maxsize=1)
    def build_report(self, blockstamp: ReferenceBlockStamp) -> tuple:
        report_data = self._calculate_report(blockstamp)
        logger.info({'msg': 'Calculate report for accounting module.', 'value': report_data})
        return report_data.as_tuple()

    # # Consensus module: if contract got report data
    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        processing_state = self._get_processing_state(blockstamp)
        logger.info({'msg': 'Check if main data was submitted.', 'value': processing_state.main_data_submitted})
        return processing_state.main_data_submitted

    # Consensus module: if contract could accept any sort of report
    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        is_reportable = not self.is_main_data_submitted(blockstamp) or not self.is_extra_data_submitted(blockstamp)
        logger.info({'msg': 'Check if contract could accept report.', 'value': is_reportable})
        return is_reportable

    def is_extra_data_submitted(self, blockstamp: BlockStamp) -> bool:
        processing_state = self._get_processing_state(blockstamp)
        return processing_state.extra_data_submitted

    @lru_cache(maxsize=1)
    def _get_processing_state(self, blockstamp: BlockStamp) -> AccountingProcessingState:
        ps = named_tuple_to_dataclass(
            self.report_contract.functions.getProcessingState().call(block_identifier=blockstamp.block_hash),
            AccountingProcessingState,
        )
        logger.info({'msg': 'Fetch processing state.', 'value': ps})
        return ps

    def _calculate_report(self, blockstamp: ReferenceBlockStamp) -> ReportData:
        validators_count, cl_balance = self._get_consensus_lido_state(blockstamp)

        staking_module_ids_list, exit_validators_count_list = self._get_newly_exited_validators_by_modules(blockstamp)

        extra_data = self.lido_validator_state_service.get_extra_data(blockstamp, self.get_chain_config(blockstamp))

        report_data = ReportData(
            consensus_version=self.CONSENSUS_VERSION,
            ref_slot=blockstamp.ref_slot,
            validators_count=validators_count,
            cl_balance_gwei=cl_balance,
            staking_module_id_with_exited_validators=staking_module_ids_list,
            count_exited_validators_by_staking_module=exit_validators_count_list,
            withdrawal_vault_balance=self.w3.lido_contracts.get_withdrawal_balance(blockstamp),
            el_rewards_vault_balance=self.w3.lido_contracts.get_el_vault_balance(blockstamp),
            shares_requested_to_burn=self.get_shares_to_burn(blockstamp),
            withdrawal_finalization_batches=self._get_withdrawal_batches(blockstamp),
            finalization_share_rate=self._get_finalization_shares_rate(blockstamp),
            is_bunker=self._is_bunker(blockstamp),
            extra_data_format=extra_data.format,
            extra_data_hash=extra_data.data_hash,
            extra_data_items_count=extra_data.items_count,
        )

        return report_data

    def _get_newly_exited_validators_by_modules(
        self,
        blockstamp: ReferenceBlockStamp,
    ) -> tuple[list[StakingModuleId], list[int]]:
        """
        Calculate exited validators count in all modules.
        Exclude modules without changes from the report.
        """
        staking_modules = self.w3.lido_validators.get_staking_modules(blockstamp)
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
    def _get_consensus_lido_state(self, blockstamp: ReferenceBlockStamp) -> tuple[int, Gwei]:
        lido_validators = self.w3.lido_validators.get_lido_validators(blockstamp)

        count = len(lido_validators)
        total_balance = Gwei(sum(int(validator.balance) for validator in lido_validators))

        logger.info({'msg': 'Calculate consensus lido state.', 'value': (count, total_balance)})
        return count, total_balance

    def _get_withdrawal_batches(self, blockstamp: ReferenceBlockStamp) -> list[int]:
        chain_config = self.get_chain_config(blockstamp)
        frame_config = self.get_frame_config(blockstamp)

        is_bunker = self._is_bunker(blockstamp)
        withdrawal_vault_balance = self.w3.lido_contracts.get_withdrawal_balance(blockstamp)
        el_rewards_vault_balance = self.w3.lido_contracts.get_el_vault_balance(blockstamp)
        finalization_share_rate = self._get_finalization_shares_rate(blockstamp)

        withdrawal_service = Withdrawal(self.w3, blockstamp, chain_config, frame_config)
        withdrawal_batches = withdrawal_service.get_finalization_batches(
            is_bunker,
            finalization_share_rate,
            withdrawal_vault_balance,
            el_rewards_vault_balance,
        )
        logger.info({'msg': 'Calculate last withdrawal id to finalize.', 'value': withdrawal_batches})
        return withdrawal_batches

    @lru_cache(maxsize=1)
    def _get_finalization_shares_rate(self, blockstamp: ReferenceBlockStamp) -> int:
        simulation = self.simulate_el_rebase(blockstamp)
        shares_rate = simulation.post_total_pooled_ether * SHARE_RATE_PRECISION_E27 // simulation.post_total_shares
        logger.info({'msg': 'Calculate shares rate.', 'value': shares_rate})
        return shares_rate

    def simulate_cl_rebase(self, blockstamp: ReferenceBlockStamp) -> LidoReportRebase:
        return self.simulate_rebase_after_report(blockstamp)

    def simulate_el_rebase(self, blockstamp: ReferenceBlockStamp) -> LidoReportRebase:
        el_rewards = self.w3.lido_contracts.get_el_vault_balance(blockstamp)
        return self.simulate_rebase_after_report(blockstamp, el_rewards=el_rewards)

    def simulate_rebase_after_report(
        self,
        blockstamp: ReferenceBlockStamp,
        el_rewards: Wei = 0,
    ) -> LidoReportRebase:
        """
        To calculate how much withdrawal request protocol can finalize - needs finalization share rate after this report
        """
        validators_count, cl_balance = self._get_consensus_lido_state(blockstamp)

        timestamp = self.get_ref_slot_timestamp(blockstamp)

        chain_conf = self.get_chain_config(blockstamp)

        simulated_tx = self.w3.lido_contracts.lido.functions.handleOracleReport(
            # Oracle timings
            timestamp,  # _reportTimestamp
            self._get_slots_elapsed_from_last_report(blockstamp) * chain_conf.seconds_per_slot,  # _timeElapsed
            # CL values
            validators_count,  # _clValidators
            Web3.to_wei(cl_balance, 'gwei'),  # _clBalance
            # EL values
            self.w3.lido_contracts.get_withdrawal_balance(blockstamp),  # _withdrawalVaultBalance
            el_rewards,  # _elRewardsVaultBalance
            self.get_shares_to_burn(blockstamp),  # _sharesRequestedToBurn
            # Decision about withdrawals processing
            [],  # _lastFinalizableRequestId
            0,  # _simulatedShareRate
        )

        logger.info({'msg': 'Simulate lido rebase for report.', 'value': simulated_tx.args})

        result = simulated_tx.call(
            transaction={'from': self.w3.lido_contracts.accounting_oracle.address},
            block_identifier=blockstamp.block_hash,
        )

        logger.info({'msg': 'Fetch simulated lido rebase for report.', 'value': result})

        return LidoReportRebase(*result)

    def get_shares_to_burn(self, blockstamp: BlockStamp) -> int:
        shares_data = named_tuple_to_dataclass(
            self.w3.lido_contracts.burner.functions.getSharesRequestedToBurn().call(
                block_identifier=blockstamp.block_hash,
            ),
            SharesRequestedToBurn,
        )

        return shares_data.cover_shares + shares_data.non_cover_shares

    def get_ref_slot_timestamp(self, blockstamp: ReferenceBlockStamp):
        chain_conf = self.get_chain_config(blockstamp)
        return chain_conf.genesis_time + blockstamp.ref_slot * chain_conf.seconds_per_slot

    def _get_slots_elapsed_from_last_report(self, blockstamp: ReferenceBlockStamp):
        """If no report was finalized return slots elapsed from initial epoch from contract"""
        chain_conf = self.get_chain_config(blockstamp)
        frame_config = self.get_frame_config(blockstamp)

        last_ref_slot = self.w3.lido_contracts.get_accounting_last_processing_ref_slot(blockstamp)

        if last_ref_slot:
            slots_elapsed = blockstamp.ref_slot - last_ref_slot
        else:
            slots_elapsed = blockstamp.ref_slot - frame_config.initial_epoch * chain_conf.slots_per_epoch

        return slots_elapsed

    @lru_cache(maxsize=1)
    def _is_bunker(self, blockstamp: ReferenceBlockStamp) -> bool:
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
        return bunker_mode
