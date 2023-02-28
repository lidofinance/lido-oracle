import logging
from collections import defaultdict
from functools import lru_cache
from time import sleep

from src import variables
from src.constants import SHARE_RATE_PRECISION_E27
from src.modules.accounting.typings import ReportData, ProcessingState, LidoReportRebase
from src.modules.accounting.validator_state import LidoValidatorStateService
from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule
from src.services.withdrawal import Withdrawal
from src.modules.accounting.bunker import BunkerService
from src.typings import BlockStamp, Gwei, ReferenceBlockStamp
from src.utils.abi import named_tuple_to_dataclass
from src.web3py.extentions.lido_validators import StakingModuleId
from src.web3py.typings import Web3


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

        if report_blockstamp:
            self.process_report(report_blockstamp)
            self.process_extra_data(report_blockstamp)
            return True

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

        tx = self.report_contract.functions.submitReportExtraDataList(extra_data.extra_data)

        if self.w3.transaction.check_transaction(tx, variables.ACCOUNT.address):
            self.w3.transaction.sign_and_send_transaction(tx, variables.ACCOUNT)

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
        return processing_state.extra_data_items_count == processing_state.extra_data_items_submitted

    @lru_cache(maxsize=1)
    def _get_processing_state(self, blockstamp: BlockStamp) -> ProcessingState:
        ps = named_tuple_to_dataclass(
            self.report_contract.functions.getProcessingState().call(block_identifier=blockstamp.block_hash),
            ProcessingState,
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
            stacking_module_id_with_exited_validators=staking_module_ids_list,
            count_exited_validators_by_stacking_module=exit_validators_count_list,
            withdrawal_vault_balance=self.w3.lido_contracts.get_withdrawal_balance(blockstamp),
            el_rewards_vault_balance=self.w3.lido_contracts.get_el_vault_balance(blockstamp),
            last_withdrawal_request_to_finalize=self._get_last_withdrawal_request_to_finalize(blockstamp),
            finalization_share_rate=self._get_finalization_shares_rate(blockstamp),
            is_bunker=self._is_bunker(blockstamp),
            extra_data_format=extra_data.format,
            extra_data_hash=extra_data.data_hash,
            extra_data_items_count=extra_data.items_count,
        )

        return report_data

    def _get_newly_exited_validators_by_modules(self, blockstamp: ReferenceBlockStamp) -> tuple[list[StakingModuleId], list[int]]:
        stacking_modules = self.w3.lido_validators.get_staking_modules(blockstamp)

        exited_validators = self.lido_validator_state_service.get_exited_lido_validators(blockstamp)

        module_stats = defaultdict(int)

        for (module_id, _), validators_exited_count in exited_validators:
            module_stats[module_id] += validators_exited_count

        for module in stacking_modules:
            if module_stats[module.id] == module.exited_validators_count:
                del module_stats[module.id]

        return tuple(zip(*module_stats.items()))

    @lru_cache(maxsize=1)
    def _get_consensus_lido_state(self, blockstamp: ReferenceBlockStamp) -> tuple[int, Gwei]:
        lido_validators = self.w3.lido_validators.get_lido_validators(blockstamp)

        count = len(lido_validators)
        total_balance = Gwei(sum(int(validator.balance) for validator in lido_validators))

        logger.info({'msg': 'Calculate consensus lido state.', 'value': (count, total_balance)})
        return count, total_balance

    def _get_last_withdrawal_request_to_finalize(self, blockstamp: ReferenceBlockStamp) -> int:
        chain_config = self.get_chain_config(blockstamp)
        frame_config = self.get_frame_config(blockstamp)

        is_bunker = self._is_bunker(blockstamp)
        withdrawal_vault_balance = self.w3.lido_contracts.get_withdrawal_balance(blockstamp)
        el_rewards_vault_balance = self.w3.lido_contracts.get_el_vault_balance(blockstamp)
        finalization_share_rate = self._get_finalization_shares_rate(blockstamp)

        withdrawal_service = Withdrawal(self.w3, blockstamp, chain_config, frame_config)

        last_wr_id = withdrawal_service.get_next_last_finalizable_id(
            is_bunker,
            finalization_share_rate,
            withdrawal_vault_balance,
            el_rewards_vault_balance,
        )
        logger.info({'msg': 'Calculate last withdrawal id to finalize.', 'value': last_wr_id})
        return last_wr_id

    @lru_cache(maxsize=1)
    def _get_finalization_shares_rate(self, blockstamp: ReferenceBlockStamp) -> int:
        simulation = self.get_rebase_after_report(blockstamp)
        shares_rate = simulation.post_total_pooled_ether * SHARE_RATE_PRECISION_E27 // simulation.post_total_shares
        logger.info({'msg': 'Calculate shares rate.', 'value': shares_rate})
        return shares_rate

    def get_rebase_after_report(self, blockstamp: ReferenceBlockStamp, cl_only=False) -> LidoReportRebase:
        chain_conf = self.get_chain_config(blockstamp)
        frame_config = self.get_frame_config(blockstamp)

        last_ref_slot = self.report_contract.functions.getLastProcessingRefSlot().call(
            block_identifier=blockstamp.block_hash,
        )

        if last_ref_slot:
            slots_elapsed = blockstamp.ref_slot - last_ref_slot
        else:
            slots_elapsed = blockstamp.ref_slot - frame_config.initial_epoch * chain_conf.slots_per_epoch

        validators_count, cl_balance = self._get_consensus_lido_state(blockstamp)

        timestamp = chain_conf.genesis_time + blockstamp.ref_slot * chain_conf.seconds_per_slot

        result = self.w3.lido_contracts.lido.functions.handleOracleReport(
            timestamp,  # _reportTimestamp
            slots_elapsed * chain_conf.seconds_per_slot,  # _timeElapsed
            validators_count,  # _clValidators
            Web3.to_wei(cl_balance, 'gwei'),  # _clBalance
            self.w3.lido_contracts.get_withdrawal_balance(blockstamp),  # _withdrawalVaultBalance
            0 if cl_only else self.w3.lido_contracts.get_el_vault_balance(blockstamp),  # _elRewardsVaultBalance
            0,  # _lastFinalizableRequestId
            0,  # _simulatedShareRate
        ).call(
            transaction={'from': self.w3.lido_contracts.accounting_oracle.address},
            block_identifier=blockstamp.block_hash,
        )

        logger.info({'msg': 'Fetch simulated lido rebase for report.', 'value': result})

        return LidoReportRebase(*result)

    def _is_bunker(self, blockstamp: ReferenceBlockStamp) -> bool:
        frame_config = self.get_frame_config(blockstamp)
        chain_config = self.get_chain_config(blockstamp)
        cl_rebase_report = self.get_rebase_after_report(blockstamp, cl_only=True)

        bunker_mode = self.bunker_service.is_bunker_mode(
            blockstamp,
            frame_config,
            chain_config,
            cl_rebase_report,
        )
        logger.info({'msg': 'Calculate bunker mode.', 'value': bunker_mode})
        return bunker_mode
