import logging
from functools import reduce

from web3.types import Wei

from src.constants import (
    FAR_FUTURE_EPOCH,
    MAX_EFFECTIVE_BALANCE,
    MAX_WITHDRAWALS_PER_PAYLOAD,
    MIN_VALIDATOR_WITHDRAWABILITY_DELAY,
)
from src.metrics.prometheus.business import CONTRACT_ON_PAUSE
from src.metrics.prometheus.ejector import (
    EJECTOR_VALIDATORS_COUNT_TO_EJECT,
    EJECTOR_TO_WITHDRAW_WEI_AMOUNT,
    EJECTOR_MAX_WITHDRAWAL_EPOCH,
)
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.ejector.data_encode import encode_data
from src.modules.ejector.types import ReportData
from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule, ModuleExecuteDelay
from src.providers.consensus.types import Validator
from src.providers.execution.contracts.exit_bus_oracle import ExitBusOracleContract
from src.services.exit_order.iterator import ExitOrderIterator
from src.services.exit_order_v2.iterator import ValidatorExitIteratorV2
from src.services.prediction import RewardsPredictionService
from src.services.validator_state import LidoValidatorStateService
from src.types import BlockStamp, EpochNumber, ReferenceBlockStamp, NodeOperatorGlobalIndex
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.validator_state import (
    is_active_validator,
    is_fully_withdrawable_validator,
    is_partially_withdrawable_validator,
    compute_activation_exit_epoch,
    compute_exit_churn_limit,
)
from src.web3py.extensions.lido_validators import LidoValidator
from src.web3py.types import Web3


logger = logging.getLogger(__name__)


class Ejector(BaseModule, ConsensusModule):
    """
    Module that ejects lido validators depends on total value of unfinalized withdrawal requests.

    Flow:
    1. Calculate withdrawals amount to cover with ETH.
    2. Calculate ETH rewards prediction per epoch.
    Loop:
        1. Calculate withdrawn epoch for last validator in "to eject" list.
        2. Calculate predicted rewards we get until last validator will be withdrawn.
        3. Check if validators to eject + predicted rewards and withdrawals + current balance is enough to finalize all withdrawal requests.
            - If True - eject all validators in list. End.
        4. Add new validator to "to eject" list.
        5. Recalculate withdrawn epoch.

    3. Decode lido validators into bytes and send report transaction
    """
    COMPATIBLE_CONTRACT_VERSIONS = [1]
    COMPATIBLE_CONSENSUS_VERSIONS = [1, 2]

    AVG_EXPECTING_WITHDRAWALS_SWEEP_DURATION_MULTIPLIER = 0.5

    def __init__(self, w3: Web3):
        self.report_contract: ExitBusOracleContract = w3.lido_contracts.validators_exit_bus_oracle

        super().__init__(w3)

        self.prediction_service = RewardsPredictionService(w3)
        self.validators_state_service = LidoValidatorStateService(w3)

    def refresh_contracts(self):
        self.report_contract = self.w3.lido_contracts.validators_exit_bus_oracle

    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        report_blockstamp = self.get_blockstamp_for_report(last_finalized_blockstamp)

        if not report_blockstamp:
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        self.process_report(report_blockstamp)
        return ModuleExecuteDelay.NEXT_SLOT

    @lru_cache(maxsize=1)
    @duration_meter()
    def build_report(self, blockstamp: ReferenceBlockStamp) -> tuple:
        # For metrics only
        self.w3.lido_contracts.get_ejector_last_processing_ref_slot(blockstamp)

        validators: list[tuple[NodeOperatorGlobalIndex, LidoValidator]] = self.get_validators_to_eject(blockstamp)
        logger.info({
            'msg': f'Calculate validators to eject. Count: {len(validators)}',
            'value': [val[1].index for val in validators]},
        )

        data, data_format = encode_data(validators)

        report_data = ReportData(
            self.report_contract.get_consensus_version(blockstamp.block_hash),
            blockstamp.ref_slot,
            len(validators),
            data_format,
            data,
        )

        EJECTOR_VALIDATORS_COUNT_TO_EJECT.set(report_data.requests_count)

        return report_data.as_tuple()

    def get_validators_to_eject(self, blockstamp: ReferenceBlockStamp) -> list[tuple[NodeOperatorGlobalIndex, LidoValidator]]:
        to_withdraw_amount = self.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth(blockstamp.block_hash)
        EJECTOR_TO_WITHDRAW_WEI_AMOUNT.set(to_withdraw_amount)
        logger.info({'msg': 'Calculate to withdraw amount.', 'value': to_withdraw_amount})

        expected_balance = self._get_total_expected_balance(0, blockstamp)

        consensus_version = self.w3.lido_contracts.validators_exit_bus_oracle.get_consensus_version(blockstamp.block_hash)
        validators_iterator = iter(self.get_validators_iterator(consensus_version, blockstamp))

        validators_to_eject: list[tuple[NodeOperatorGlobalIndex, LidoValidator]] = []
        validator_to_eject_balance_sum = 0

        try:
            while expected_balance < to_withdraw_amount:
                gid, next_validator = next(validators_iterator)
                validators_to_eject.append((gid, next_validator))
                validator_to_eject_balance_sum += self._get_predicted_withdrawable_balance(next_validator)
                expected_balance = self._get_total_expected_balance(len(validators_to_eject), blockstamp) + validator_to_eject_balance_sum
        except StopIteration:
            pass

        logger.info({
            'msg': 'Calculate validators to eject',
            'expected_balance': expected_balance,
            'to_withdraw_amount': to_withdraw_amount,
            'validators_to_eject_count': len(validators_to_eject),
        })

        if consensus_version != 1:
            forced_validators = validators_iterator.get_remaining_forced_validators()
            if forced_validators:
                logger.info({'msg': 'Eject forced to exit validators.', 'value': len(forced_validators)})
                validators_to_eject.extend(forced_validators)

        return validators_to_eject

    def _get_total_expected_balance(self, vals_to_exit: int, blockstamp: ReferenceBlockStamp):
        chain_config = self.get_chain_config(blockstamp)

        validators_going_to_exit = self.validators_state_service.get_recently_requested_but_not_exited_validators(blockstamp, chain_config)
        going_to_withdraw_balance = sum(map(
            self._get_predicted_withdrawable_balance,
            validators_going_to_exit,
        ))
        logger.info({'msg': 'Calculate going to exit validators balance.', 'value': going_to_withdraw_balance})

        epochs_to_sweep = self._get_sweep_delay_in_epochs(blockstamp)
        logger.info({'msg': 'Calculate epochs to sweep.', 'value': epochs_to_sweep})

        rewards_speed_per_epoch = self.prediction_service.get_rewards_per_epoch(blockstamp, chain_config)
        logger.info({'msg': 'Calculate average rewards speed per epoch.', 'value': rewards_speed_per_epoch})

        withdrawal_epoch = self._get_predicted_withdrawable_epoch(blockstamp, len(validators_going_to_exit) + vals_to_exit + 1)
        logger.info({'msg': 'Withdrawal epoch', 'value': withdrawal_epoch})
        EJECTOR_MAX_WITHDRAWAL_EPOCH.set(withdrawal_epoch)

        future_withdrawals = self._get_withdrawable_lido_validators_balance(withdrawal_epoch, blockstamp)
        future_rewards = (withdrawal_epoch + epochs_to_sweep - blockstamp.ref_epoch) * rewards_speed_per_epoch
        logger.info({'msg': 'Calculate future rewards.', 'value': future_rewards})

        total_available_balance = self._get_total_el_balance(blockstamp)
        logger.info({'msg': 'Calculate el balance.', 'value': total_available_balance})

        return future_rewards + future_withdrawals + total_available_balance + going_to_withdraw_balance

    def get_validators_iterator(self, consensus_version: int,  blockstamp: ReferenceBlockStamp):
        chain_config = self.get_chain_config(blockstamp)

        if consensus_version == 1:
            return ExitOrderIterator(
                web3=self.w3,
                blockstamp=blockstamp,
                chain_config=chain_config
            )

        return ValidatorExitIteratorV2(
            w3=self.w3,
            blockstamp=blockstamp,
            seconds_per_slot=chain_config.seconds_per_slot
        )

    def is_reporting_allowed(self, blockstamp: ReferenceBlockStamp) -> bool:
        on_pause = self.report_contract.is_paused('latest')
        CONTRACT_ON_PAUSE.labels('vebo').set(on_pause)
        logger.info({'msg': 'Fetch isPaused from ejector bus contract.', 'value': on_pause})
        return not on_pause

    @lru_cache(maxsize=1)
    def _get_withdrawable_lido_validators_balance(self, on_epoch: EpochNumber, blockstamp: BlockStamp) -> Wei:
        lido_validators = self.w3.lido_validators.get_lido_validators(blockstamp=blockstamp)

        def get_total_withdrawable_balance(balance: Wei, validator: Validator) -> Wei:
            if is_fully_withdrawable_validator(validator, on_epoch):
                return Wei(balance + self._get_predicted_withdrawable_balance(validator))

            return balance

        result = reduce(
            get_total_withdrawable_balance,
            lido_validators,
            Wei(0),
        )

        return result

    def _get_predicted_withdrawable_balance(self, validator: Validator) -> Wei:
        return self.w3.to_wei(min(int(validator.balance), MAX_EFFECTIVE_BALANCE), 'gwei')

    @lru_cache(maxsize=1)
    def _get_total_el_balance(self, blockstamp: BlockStamp) -> Wei:
        return Wei(
            self.w3.lido_contracts.get_el_vault_balance(blockstamp) +
            self.w3.lido_contracts.get_withdrawal_balance(blockstamp) +
            self.w3.lido_contracts.lido.get_buffered_ether(blockstamp.block_hash)
        )

    def _get_predicted_withdrawable_epoch(
        self,
        blockstamp: ReferenceBlockStamp,
        validators_to_eject_count: int,
    ) -> EpochNumber:
        """
        Returns epoch when all validators in queue and validators_to_eject will be withdrawn.
        """
        max_exit_epoch_number, latest_to_exit_validators_count = self._get_latest_exit_epoch(blockstamp)

        activation_exit_epoch = compute_activation_exit_epoch(blockstamp.ref_epoch)

        if activation_exit_epoch > max_exit_epoch_number:
            max_exit_epoch_number = activation_exit_epoch
            latest_to_exit_validators_count = 0

        churn_limit = self._get_churn_limit(blockstamp)

        epochs_required_to_exit_validators = (validators_to_eject_count + latest_to_exit_validators_count) // churn_limit

        return EpochNumber(max_exit_epoch_number + epochs_required_to_exit_validators + MIN_VALIDATOR_WITHDRAWABILITY_DELAY)

    @lru_cache(maxsize=1)
    def _get_latest_exit_epoch(self, blockstamp: ReferenceBlockStamp) -> tuple[EpochNumber, int]:
        """
        Returns the latest exit epoch and amount of validators that are exiting in this epoch
        """
        max_exit_epoch_number = EpochNumber(0)
        latest_to_exit_validators_count = 0

        validators = self.w3.cc.get_validators(blockstamp)

        for validator in validators:
            val_exit_epoch = EpochNumber(int(validator.validator.exit_epoch))

            if val_exit_epoch == FAR_FUTURE_EPOCH:
                continue

            if val_exit_epoch == max_exit_epoch_number:
                latest_to_exit_validators_count += 1

            elif val_exit_epoch > max_exit_epoch_number:
                max_exit_epoch_number = val_exit_epoch
                latest_to_exit_validators_count = 1

        logger.info({
            'msg': 'Calculate latest exit epoch',
            'value': max_exit_epoch_number,
            'latest_to_exit_validators_count': latest_to_exit_validators_count,
        })

        return max_exit_epoch_number, latest_to_exit_validators_count

    @lru_cache(maxsize=1)
    def _get_sweep_delay_in_epochs(self, blockstamp: ReferenceBlockStamp) -> int:
        """Returns amount of epochs that will take to sweep all validators in chain."""
        chain_config = self.get_chain_config(blockstamp)
        total_withdrawable_validators = self._get_total_withdrawable_validators(blockstamp)

        full_sweep_in_epochs = total_withdrawable_validators / MAX_WITHDRAWALS_PER_PAYLOAD / chain_config.slots_per_epoch
        return int(full_sweep_in_epochs * self.AVG_EXPECTING_WITHDRAWALS_SWEEP_DURATION_MULTIPLIER)

    def _get_total_withdrawable_validators(self, blockstamp: ReferenceBlockStamp) -> int:
        total_withdrawable_validators = len(list(filter(lambda validator: (
            is_partially_withdrawable_validator(validator) or
            is_fully_withdrawable_validator(validator, blockstamp.ref_epoch)
        ), self.w3.cc.get_validators(blockstamp))))

        logger.info({'msg': 'Calculate total withdrawable validators.', 'value': total_withdrawable_validators})
        return total_withdrawable_validators

    @lru_cache(maxsize=1)
    def _get_churn_limit(self, blockstamp: ReferenceBlockStamp) -> int:
        total_active_validators = self._get_total_active_validators(blockstamp)
        churn_limit = compute_exit_churn_limit(total_active_validators)
        logger.info({'msg': 'Calculate churn limit.', 'value': churn_limit})
        return churn_limit

    def _get_total_active_validators(self, blockstamp: ReferenceBlockStamp) -> int:
        total_active_validators = len([
            is_active_validator(val, blockstamp.ref_epoch)
            for val in self.w3.cc.get_validators(blockstamp)
        ])
        logger.info({'msg': 'Calculate total active validators.', 'value': total_active_validators})
        return total_active_validators

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        processing_state = self.report_contract.get_processing_state(blockstamp.block_hash)
        return processing_state.data_submitted

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        return not self.is_main_data_submitted(blockstamp)
