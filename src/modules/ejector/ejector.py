import logging
from functools import lru_cache, reduce

from web3.types import Wei

from src.constants import (
    MAX_WITHDRAWALS_PER_PAYLOAD,
    ETH1_ADDRESS_WITHDRAWAL_PREFIX,
    MIN_PER_EPOCH_CHURN_LIMIT,
    CHURN_LIMIT_QUOTIENT, FAR_FUTURE_EPOCH, MIN_VALIDATOR_WITHDRAWABILITY_DELAY,
)
from src.modules.ejector.data_encode import encode_data
from src.modules.ejector.prediction import RewardsPredictionService
from src.modules.ejector.typings import ProcessingState, ReportData
from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule
from src.providers.consensus.typings import Validator
from src.typings import BlockStamp, EpochNumber
from src.utils.abi import named_tuple_to_dataclass
from src.utils.validator_state import is_validator_active
from src.web3py.extentions.lido_validators import LidoValidator, NodeOperatorIndex
from src.web3py.typings import Web3


logger = logging.getLogger(__name__)


class Ejector(BaseModule, ConsensusModule):
    """
    1. Get withdrawals amount
    2. Get exit prediction
    Loop:
     a. Get validator
     b. Remove withdrawal amount
     c. Increase order
     d. Check new withdrawals epoches
     e. If withdrawals ok - exit
    3. Decode gotten lido validators
    4. Send hash + send data
    """
    CONSENSUS_VERSION = 1
    CONTRACT_VERSION = 1

    AVG_EXPECTING_TIME_IN_SWEEP_MULTIPLIER = 0.5

    def __init__(self, w3: Web3):
        self.report_contract = w3.lido_contracts.validators_exit_bus_oracle
        super().__init__(w3)

        self.prediction_service = RewardsPredictionService(w3)

    def execute_module(self, blockstamp: BlockStamp):
        self.process_report(blockstamp)
        report_blockstamp = self.get_blockstamp_for_report(blockstamp)
        if report_blockstamp:
            self.process_report(report_blockstamp)

    @lru_cache(maxsize=1)
    def build_report(self, blockstamp: BlockStamp) -> tuple:
        validators = self.get_validators_to_eject(blockstamp)

        data, data_format = encode_data(validators)

        return ReportData(
            self.CONSENSUS_VERSION,
            blockstamp.ref_slot,
            len(validators),
            data_format,
            data,
        ).as_tuple()

    def get_validators_to_eject(self, blockstamp: BlockStamp) -> list[tuple[NodeOperatorIndex, LidoValidator]]:
        chain_config = self._get_chain_config(blockstamp)

        rewards_speed_per_epoch = self.prediction_service.get_rewards_per_epoch(blockstamp, chain_config)
        epochs_to_sweep = self._get_sweep_delay_in_epochs(blockstamp)

        to_withdraw_amount = self.get_total_unfinalized_withdrawal_requests_amount(blockstamp)
        total_current_balance = self._get_total_balance(blockstamp)

        validators_to_eject = []
        validator_to_eject_balance_sum = 0
        # ToDo replace it with exit order
        exit_order: list[tuple[NodeOperatorIndex, LidoValidator]] = []
        for no_index, validator in exit_order:
            withdrawal_epoch = self._get_withdrawal_epoch_for_latest_validator(blockstamp, len(validators_to_eject) + 1)
            future_rewards = (blockstamp.ref_slot - (withdrawal_epoch + epochs_to_sweep)) * rewards_speed_per_epoch

            if future_rewards + total_current_balance + validator_to_eject_balance_sum >= to_withdraw_amount:
                return validators_to_eject

            validators_to_eject.append((no_index, validator))
            validator_to_eject_balance_sum += int(validator.validator.validator.effective_balance)

        return validators_to_eject

    @lru_cache(maxsize=1)
    def _get_total_balance(self, blockstamp: BlockStamp) -> Wei:
        return Wei(
            self._get_withdrawal_balance(blockstamp) +
            self._get_el_vault_balance(blockstamp) +
            self._get_reserved_buffer(blockstamp)
        )

    def _get_withdrawal_balance(self, blockstamp: BlockStamp) -> Wei:
        return Wei(self.w3.eth.get_balance(
            self.w3.lido_contracts.lido_locator.functions.withdrawalVault().call(
                block_identifier=blockstamp.block_hash
            ),
            block_identifier=blockstamp.block_hash,
        ))

    def _get_el_vault_balance(self, blockstamp: BlockStamp) -> Wei:
        return Wei(self.w3.eth.get_balance(
            self.w3.lido_contracts.lido_locator.functions.elRewardsVault().call(
                block_identifier=blockstamp.block_hash
            ),
            block_identifier=blockstamp.block_hash,
        ))

    def _get_reserved_buffer(self, blockstamp: BlockStamp) -> Wei:
        return Wei(
            self.w3.lido_contracts.lido.functions.getBufferedEther().call(
                block_identifier=blockstamp.block_hash
            )
        )

    def get_total_unfinalized_withdrawal_requests_amount(self, blockstamp: BlockStamp) -> Wei:
        steth_to_finalize = self.w3.lido_contracts.withdrawal_queue_nft.functions.unfinalizedStETH().call(
            block_identifier=blockstamp.block_hash,
        )
        logger.info({'msg': 'Wei to finalize.'})
        return steth_to_finalize

    def _get_withdrawal_epoch_for_latest_validator(self, blockstamp: BlockStamp, validators_to_eject_count: int) -> EpochNumber:
        max_exit_epoch_number = 0
        latest_to_exit_validators_count = 0

        for validator in self.w3.cc.get_validators(blockstamp.state_root):
            val_exit_epoch = EpochNumber(int(validator.validator.exit_epoch))

            if val_exit_epoch == FAR_FUTURE_EPOCH:
                continue

            if val_exit_epoch == max_exit_epoch_number:
                latest_to_exit_validators_count += 1

            elif val_exit_epoch > max_exit_epoch_number:
                max_exit_epoch_number = val_exit_epoch
                latest_to_exit_validators_count = 1

        churn_limit = self._get_churn_limit(blockstamp)

        free_slots_in_current_epoch = churn_limit - latest_to_exit_validators_count
        need_to_exit_all_epochs = (validators_to_eject_count - free_slots_in_current_epoch) // churn_limit + 1

        return EpochNumber(max_exit_epoch_number + need_to_exit_all_epochs + MIN_VALIDATOR_WITHDRAWABILITY_DELAY)

    def _get_sweep_delay_in_epochs(self, blockstamp: BlockStamp):
        validators = self.w3.cc.get_validators(blockstamp.state_root)

        def if_validators_balance_withdrawable(validator: Validator):
            if int(validator.validator.activation_epoch) > blockstamp.ref_epoch:
                return False

            if int(validator.balance) == 0:
                return False

            if validator.validator.withdrawal_credentials[:4] != ETH1_ADDRESS_WITHDRAWAL_PREFIX:
                return False

            return True

        validators_count = len(list(filter(if_validators_balance_withdrawable, validators)))
        chain_config = self._get_chain_config(blockstamp)
        return int(validators_count * self.AVG_EXPECTING_TIME_IN_SWEEP_MULTIPLIER / MAX_WITHDRAWALS_PER_PAYLOAD / chain_config.slots_per_epoch)

    def _get_churn_limit(self, blockstamp: BlockStamp) -> int:
        total_active_validators = reduce(
            lambda total, validator: total + int(is_validator_active(validator, blockstamp.ref_epoch)),
            self.w3.cc.get_validators(blockstamp.state_root),
            0,
        )
        return max(MIN_PER_EPOCH_CHURN_LIMIT, total_active_validators // CHURN_LIMIT_QUOTIENT)

    @lru_cache(maxsize=1)
    def _get_processing_state(self, blockstamp: BlockStamp) -> ProcessingState:
        return named_tuple_to_dataclass(
            self.report_contract.functions.getProcessingState().call(block_identifier=blockstamp.block_hash),
            ProcessingState,
        )

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        processing_state = self._get_processing_state(blockstamp)
        return processing_state.data_submitted

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        return self.is_main_data_submitted(blockstamp)
