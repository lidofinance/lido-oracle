import logging
from functools import lru_cache

from web3.types import Wei

from src import variables
from src.constants import SHARE_RATE_PRECISION_E27
from src.modules.accounting.typings import ReportData, ProcessingState, LidoReportRebase
from src.modules.accounting.validator_state import LidoValidatorStateService
from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule
from src.services.bunker import BunkerService
from src.services.withdrawal import Withdrawal
from src.modules.accounting.bunker import BunkerService
from src.typings import BlockStamp, Gwei
from src.utils.abi import named_tuple_to_dataclass
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
        self.withdrawal_service = Withdrawal(self.w3)

    # Oracle module: loop method
    def execute_module(self, blockstamp: BlockStamp) -> None:
        report_blockstamp = self.get_blockstamp_for_report(blockstamp)
        if report_blockstamp:
            self.process_report(report_blockstamp)

            latest_blockstamp = self._get_latest_blockstamp()
            if not self.is_extra_data_submitted(latest_blockstamp):
                self._submit_extra_data(report_blockstamp)

    def _submit_extra_data(self, blockstamp: BlockStamp) -> None:
        extra_data = self.lido_validator_state_service.get_extra_data(blockstamp, self._get_chain_config(blockstamp))

        tx = self.report_contract.functions.submitReportExtraDataList(extra_data.extra_data)

        if self.w3.transaction.check_transaction(tx, variables.ACCOUNT.address):
            self.w3.transaction.sign_and_send_transaction(tx, variables.GAS_LIMIT, variables.ACCOUNT)

    # Consensus module: main build report method
    @lru_cache(maxsize=1)
    def build_report(self, blockstamp: BlockStamp) -> tuple:
        logger.info({'msg': 'Calculate report for accounting module.'})
        report_data = self._calculate_report(blockstamp)
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

    @lru_cache(maxsize=1)
    def _get_processing_state(self, blockstamp: BlockStamp) -> ProcessingState:
        ps = named_tuple_to_dataclass(
            self.report_contract.functions.getProcessingState().call(block_identifier=blockstamp.block_hash),
            ProcessingState,
        )
        logger.info({'msg': 'Fetch processing state.', 'value': ps})
        return ps

    def is_extra_data_submitted(self, blockstamp: BlockStamp) -> bool:
        processing_state = self._get_processing_state(blockstamp)
        return processing_state.extra_data_items_count == processing_state.extra_data_items_submitted

    def _calculate_report(self, blockstamp: BlockStamp) -> ReportData:
        validators_count, cl_balance = self._get_consensus_lido_state(blockstamp)

        finalization_share_rate = self._get_finalization_shares_rate(blockstamp)
        last_withdrawal_id_to_finalize = self._get_last_withdrawal_request_to_finalize(blockstamp)

        exited_validators = self.lido_validator_state_service.get_lido_new_exited_validators(blockstamp)

        # Here report all exited validators even they were reported before.
        if exited_validators:
            stacking_module_id_list, exit_validators_count_list = zip(*exited_validators.items())
        else:
            stacking_module_id_list = exit_validators_count_list = []

        extra_data = self.lido_validator_state_service.get_extra_data(blockstamp, self._get_chain_config(blockstamp))

        # Filter stuck and exited validators that was previously reported
        report_data = ReportData(
            consensus_version=self.CONSENSUS_VERSION,
            ref_slot=blockstamp.ref_slot,
            validators_count=validators_count,
            cl_balance_gwei=cl_balance,
            stacking_module_id_with_exited_validators=stacking_module_id_list,
            count_exited_validators_by_stacking_module=exit_validators_count_list,
            withdrawal_vault_balance=self._get_withdrawal_balance(blockstamp),
            el_rewards_vault_balance=self._get_el_vault_balance(blockstamp),
            last_withdrawal_request_to_finalize=last_withdrawal_id_to_finalize,
            finalization_share_rate=finalization_share_rate,
            is_bunker=self._is_bunker(blockstamp),
            extra_data_format=extra_data.format,
            extra_data_hash=extra_data.data_hash,
            extra_data_items_count=extra_data.items_count,
        )

        return report_data

    @lru_cache(maxsize=1)
    def _get_consensus_lido_state(self, blockstamp: BlockStamp) -> tuple[int, Gwei]:
        lido_validators = self.w3.lido_validators.get_lido_validators(blockstamp)

        count = len(lido_validators)
        balance = Gwei(sum(int(validator.validator.balance) for validator in lido_validators))
        return count, balance

    @lru_cache(maxsize=1)
    def _get_withdrawal_balance(self, blockstamp: BlockStamp) -> Wei:
        return Wei(self.w3.eth.get_balance(
            self.w3.lido_contracts.lido_locator.functions.withdrawalVault().call(
                block_identifier=blockstamp.block_hash
            ),
            block_identifier=blockstamp.block_hash,
        ))

    @lru_cache(maxsize=1)
    def _get_el_vault_balance(self, blockstamp: BlockStamp) -> Wei:
        return Wei(self.w3.eth.get_balance(
            self.w3.lido_contracts.lido_locator.functions.elRewardsVault().call(
                block_identifier=blockstamp.block_hash
            ),
            block_identifier=blockstamp.block_hash,
        ))

    def _get_last_withdrawal_request_to_finalize(self, blockstamp: BlockStamp) -> int:
        is_bunker = self._is_bunker(blockstamp)
        withdrawal_vault_balance = self._get_withdrawal_balance(blockstamp)
        el_rewards_vault_balance = self._get_el_vault_balance(blockstamp)
        finalization_share_rate = self._get_finalization_shares_rate(blockstamp)
        chain_config = self._get_chain_config(blockstamp)
        frame_config = self._get_frame_config(blockstamp)

        return self.withdrawal_service.get_next_last_finalizable_id(
            is_bunker, 
            finalization_share_rate, 
            withdrawal_vault_balance, 
            el_rewards_vault_balance, 
            blockstamp,
            chain_config,
            frame_config
        )

    @lru_cache(maxsize=1)
    def _get_finalization_shares_rate(self, blockstamp: BlockStamp) -> int:
        simulation = self.get_rebase_after_report(blockstamp)
        return simulation.post_total_pooled_ether * SHARE_RATE_PRECISION_E27 // simulation.post_total_shares

    @lru_cache(maxsize=1)
    def get_rebase_after_report(self, blockstamp: BlockStamp) -> LidoReportRebase:
        chain_conf = self._get_chain_config(blockstamp)
        frame_config = self._get_frame_config(blockstamp)

        last_ref_slot = self.report_contract.functions.getLastProcessingRefSlot().call(
            block_identifier=blockstamp.block_hash,
        )

        if not last_ref_slot:
            slots_elapsed = frame_config.epochs_per_frame * chain_conf.slots_per_epoch
        else:
            slots_elapsed = blockstamp.ref_slot - last_ref_slot

        validators_count, cl_balance = self._get_consensus_lido_state(blockstamp)

        timestamp = chain_conf.genesis_time + blockstamp.ref_slot * chain_conf.seconds_per_slot

        result = self.w3.lido_contracts.lido.functions.handleOracleReport(
            timestamp,  # _reportTimestamp
            slots_elapsed * chain_conf.seconds_per_slot,  # _timeElapsed
            validators_count,  # _clValidators
            Web3.to_wei(cl_balance, 'gwei'),  # _clBalance
            self._get_withdrawal_balance(blockstamp),  # _withdrawalVaultBalance
            self._get_el_vault_balance(blockstamp),  # _elRewardsVaultBalance
            0,  # _lastFinalizableRequestId
            0,  # _simulatedShareRate
        ).call({'from': self.w3.lido_contracts.accounting_oracle.address})

        return LidoReportRebase(*result)

    def _is_bunker(self, blockstamp: BlockStamp) -> bool:
        frame_config = self._get_frame_config(blockstamp)
        chain_config = self._get_chain_config(blockstamp)
        rebase_report = self.get_rebase_after_report(blockstamp)

        bunker_mode = self.bunker_service.is_bunker_mode(
            blockstamp, frame_config, chain_config, rebase_report, self._previous_finalized_slot_number
        )
        logger.info({'msg': 'Calculate bunker mode.', 'value': bunker_mode})
        return bunker_mode
