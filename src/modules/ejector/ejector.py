import logging
from functools import lru_cache, reduce

from web3.types import Wei

from src.constants import (
    MAX_WITHDRAWALS_PER_PAYLOAD,
    MIN_PER_EPOCH_CHURN_LIMIT,
    CHURN_LIMIT_QUOTIENT, FAR_FUTURE_EPOCH, MIN_VALIDATOR_WITHDRAWABILITY_DELAY, MAX_EFFECTIVE_BALANCE,
    MAX_SEED_LOOKAHEAD,
)
from src.modules.ejector.data_encode import encode_data
from src.modules.ejector.prediction import RewardsPredictionService
from src.modules.ejector.typings import ProcessingState, ReportData
from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule
from src.providers.consensus.typings import Validator
from src.services.exit_order import ValidatorToExitIterator
from src.typings import BlockStamp, EpochNumber, ReferenceBlockStamp, Gwei
from src.utils.abi import named_tuple_to_dataclass
from src.utils.validator_state import is_active_validator, is_partially_withdrawable_validator, \
    is_fully_withdrawable_validator
from src.web3py.extentions.lido_validators import LidoValidator, NodeOperatorGlobalIndex
from src.web3py.typings import Web3


logger = logging.getLogger(__name__)


class Ejector(BaseModule, ConsensusModule):
    """
    Module that ejects lido validators depends on withdrawal requests stETH value.

    Flow:
    1. Calculate withdrawals amount to cover with ETH.
    2. Calculate ETH rewards prediction per epoch.
    3. Calculate withdraw epoch for next validator
    Loop:
        a. Calculate predicted rewards we get until we reach withdraw epoch
        b. Check if validators to eject + predicted rewards + current balance is enough to finalize withdrawal requests
            - If True - eject all validators in list. End.
        c. Get next validator to eject.
        d. Recalculate withdraw epoch

    4. Decode lido validators into bytes and send report transaction
    """
    CONSENSUS_VERSION = 1
    CONTRACT_VERSION = 1

    AVG_EXPECTING_WITHDRAWALS_SWEEP_DURATION_MULTIPLIER = 0.5

    def __init__(self, w3: Web3):
        self.report_contract = w3.lido_contracts.validators_exit_bus_oracle
        super().__init__(w3)

        self.prediction_service = RewardsPredictionService(w3)

    def execute_module(self, blockstamp: BlockStamp) -> bool:
        report_blockstamp = self.get_blockstamp_for_report(blockstamp)
        if report_blockstamp:
            self.process_report(report_blockstamp)
            return True
        return False

    @lru_cache(maxsize=1)
    def build_report(self, blockstamp: ReferenceBlockStamp) -> tuple:
        validators = self.get_validators_to_eject(blockstamp)

        data, data_format = encode_data(validators)

        return ReportData(
            self.CONSENSUS_VERSION,
            blockstamp.ref_slot,
            len(validators),
            data_format,
            data,
        ).as_tuple()

    def get_validators_to_eject(self, blockstamp: ReferenceBlockStamp) -> list[tuple[NodeOperatorGlobalIndex, LidoValidator]]:
        chain_config = self.get_chain_config(blockstamp)

        rewards_speed_per_epoch = self.prediction_service.get_rewards_per_epoch(blockstamp, chain_config)
        epochs_to_sweep = self._get_sweep_delay_in_epochs(blockstamp)

        to_withdraw_amount = self.get_total_unfinalized_withdrawal_requests_amount(blockstamp)
        total_current_balance = self._get_total_balance(blockstamp)

        validators_to_eject = []
        validator_to_eject_balance_sum = 0

        validators_iterator = ValidatorToExitIterator(
            w3=self.w3,
            blockstamp=blockstamp,
            c_conf=chain_config,
        )

        for validator in validators_iterator:
            withdrawal_epoch = self._get_predicted_withdrawable_epoch(blockstamp, len(validators_to_eject) + 1)
            future_rewards = (withdrawal_epoch + epochs_to_sweep - blockstamp.ref_epoch) * rewards_speed_per_epoch

            future_withdrawals = self._get_withdrawable_lido_validators(blockstamp, withdrawal_epoch)

            if future_withdrawals + future_rewards + total_current_balance + validator_to_eject_balance_sum >= to_withdraw_amount:
                return validators_to_eject

            validators_to_eject.append(validator)
            validator_to_eject_balance_sum += min(int(validator[1].balance), MAX_EFFECTIVE_BALANCE)

        return validators_to_eject

    @lru_cache(maxsize=1)
    def _get_withdrawable_lido_validators(self, blockstamp: BlockStamp, on_epoch: EpochNumber) -> Wei:
        lido_validators = self.w3.lido_validators.get_lido_validators(blockstamp=blockstamp)

        def get_total_withdrawable_balance(balance: Gwei, validator: Validator) -> Gwei:
            withdrawable_balance = min(int(validator.balance), MAX_EFFECTIVE_BALANCE) if is_fully_withdrawable_validator(validator, on_epoch) else 0
            return Gwei(balance + withdrawable_balance)

        result = reduce(
            get_total_withdrawable_balance,
            lido_validators,
            Gwei(0),
        )

        return self.w3.to_wei(result, 'gwei')

    def _get_total_balance(self, blockstamp: BlockStamp) -> Wei:
        return Wei(
            self.w3.lido_contracts.get_el_vault_balance(blockstamp) +
            self.w3.lido_contracts.get_withdrawal_balance(blockstamp) +
            self._get_reserved_buffer(blockstamp)
        )

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
        logger.info({'msg': 'Wei to finalize.', 'value': steth_to_finalize})
        return steth_to_finalize

    def _get_predicted_withdrawable_epoch(
            self,
            blockstamp: ReferenceBlockStamp,
            validators_to_eject_count: int,
    ) -> EpochNumber:
        """
        Returns epoch when all validators in queue and validators_to_eject will be withdrawn.
        """
        max_exit_epoch_number, latest_to_exit_validators_count = self._get_latest_exit_epoch(blockstamp)

        # If order is empty exit epoch is current epoch + MAX_SEED_LOOKAHEAD + 1
        max_exit_epoch_number = max(max_exit_epoch_number, self.compute_activation_exit_epoch(blockstamp))

        churn_limit = self._get_churn_limit(blockstamp)

        free_slots_in_current_epoch = churn_limit - latest_to_exit_validators_count
        need_to_exit_all_epochs = (validators_to_eject_count - free_slots_in_current_epoch) // churn_limit + 1

        return EpochNumber(max_exit_epoch_number + need_to_exit_all_epochs + MIN_VALIDATOR_WITHDRAWABILITY_DELAY)

    def compute_activation_exit_epoch(self, blockstamp: BlockStamp):
        chain_config = self.get_chain_config(blockstamp)
        latest_blockstamp = self._get_latest_blockstamp()
        return latest_blockstamp.slot_number // chain_config.slots_per_epoch + 1 + MAX_SEED_LOOKAHEAD

    @lru_cache(maxsize=1)
    def _get_latest_exit_epoch(self, blockstamp: BlockStamp) -> tuple[EpochNumber, int]:
        """
        Returns the latest exit epoch and amount of validators that are exiting in this epoch
        """
        max_exit_epoch_number = 0
        latest_to_exit_validators_count = 0

        for validator in self.w3.cc.get_validators(blockstamp):
            val_exit_epoch = EpochNumber(int(validator.validator.exit_epoch))

            if val_exit_epoch == FAR_FUTURE_EPOCH:
                continue

            if val_exit_epoch == max_exit_epoch_number:
                latest_to_exit_validators_count += 1

            elif val_exit_epoch > max_exit_epoch_number:
                max_exit_epoch_number = val_exit_epoch
                latest_to_exit_validators_count = 1

        return max_exit_epoch_number, latest_to_exit_validators_count

    def _get_sweep_delay_in_epochs(self, blockstamp: ReferenceBlockStamp):
        validators = self.w3.cc.get_validators(blockstamp)

        total_withdrawable_validators = len(list(filter(lambda validator: (
            is_partially_withdrawable_validator(validator) or
            is_fully_withdrawable_validator(validator, blockstamp.ref_epoch)
        ), validators)))

        chain_config = self.get_chain_config(blockstamp)
        return int(total_withdrawable_validators * self.AVG_EXPECTING_WITHDRAWALS_SWEEP_DURATION_MULTIPLIER / MAX_WITHDRAWALS_PER_PAYLOAD / chain_config.slots_per_epoch)

    @lru_cache(maxsize=1)
    def _get_churn_limit(self, blockstamp: ReferenceBlockStamp) -> int:
        total_active_validators = reduce(
            lambda total, validator: total + int(is_active_validator(validator, blockstamp.ref_epoch)),
            self.w3.cc.get_validators(blockstamp),
            0,
        )
        return max(MIN_PER_EPOCH_CHURN_LIMIT, total_active_validators // CHURN_LIMIT_QUOTIENT)

    def _get_processing_state(self, blockstamp: BlockStamp) -> ProcessingState:
        return named_tuple_to_dataclass(
            self.report_contract.functions.getProcessingState().call(block_identifier=blockstamp.block_hash),
            ProcessingState,
        )

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        processing_state = self._get_processing_state(blockstamp)
        return processing_state.data_submitted

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        return not self.is_main_data_submitted(blockstamp)
