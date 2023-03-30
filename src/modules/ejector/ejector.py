import logging
from functools import lru_cache, reduce

from web3.types import Wei

from src.constants import (
    CHURN_LIMIT_QUOTIENT,
    FAR_FUTURE_EPOCH,
    MAX_EFFECTIVE_BALANCE,
    MAX_SEED_LOOKAHEAD,
    MAX_WITHDRAWALS_PER_PAYLOAD,
    MIN_PER_EPOCH_CHURN_LIMIT,
    MIN_VALIDATOR_WITHDRAWABILITY_DELAY,
)
from src.metrics.prometheus.business import CONTRACT_ON_PAUSE, FRAME_PREV_REPORT_REF_SLOT
from src.metrics.prometheus.ejector import (
    EJECTOR_VALIDATORS_COUNT_TO_EJECT,
    EJECTOR_TO_WITHDRAW_WEI_AMOUNT,
    EJECTOR_MAX_EXIT_EPOCH
)
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.ejector.data_encode import encode_data
from src.modules.ejector.typings import EjectorProcessingState, ReportData
from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule, ModuleExecuteDelay
from src.providers.consensus.typings import Validator
from src.services.exit_order import ExitOrderIterator
from src.services.prediction import RewardsPredictionService
from src.services.validator_state import LidoValidatorStateService
from src.typings import BlockStamp, EpochNumber, ReferenceBlockStamp
from src.utils.abi import named_tuple_to_dataclass
from src.utils.cache import clear_object_lru_cache
from src.utils.validator_state import (
    is_active_validator,
    is_fully_withdrawable_validator,
    is_partially_withdrawable_validator,
)
from src.web3py.extensions.lido_validators import LidoValidator, NodeOperatorGlobalIndex
from src.web3py.typings import Web3

logger = logging.getLogger(__name__)


class Ejector(BaseModule, ConsensusModule):
    """
    Module that ejects lido validators depends on withdrawal requests stETH value.

    Flow:
    1. Calculate withdrawals amount to cover with ETH.
    2. Calculate ETH rewards prediction per epoch.
    3. Calculate withdrawn epoch for next validator
    Loop:
        a. Calculate predicted rewards we get until we reach withdrawn epoch
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
        self.validators_state_service = LidoValidatorStateService(w3)

    def refresh_contracts(self):
        self.report_contract = self.w3.lido_contracts.validators_exit_bus_oracle

    def clear_cache(self):
        clear_object_lru_cache(self)
        clear_object_lru_cache(self.prediction_service)
        clear_object_lru_cache(self.validators_state_service)

    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        report_blockstamp = self.get_blockstamp_for_report(last_finalized_blockstamp)
        if not report_blockstamp:
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        self.process_report(report_blockstamp)
        return ModuleExecuteDelay.NEXT_SLOT

    @lru_cache(maxsize=1)
    @duration_meter()
    def build_report(self, blockstamp: ReferenceBlockStamp) -> tuple:
        last_report_ref_slot = self.w3.lido_contracts.get_ejector_last_processing_ref_slot(blockstamp)
        FRAME_PREV_REPORT_REF_SLOT.set(last_report_ref_slot)
        validators: list[tuple[NodeOperatorGlobalIndex, LidoValidator]] = self.get_validators_to_eject(blockstamp)
        logger.info({
            'msg': f'Calculate validators to eject. Count: {len(validators)}',
            'value': [val[1].index for val in validators]},
        )

        data, data_format = encode_data(validators)

        report_data = ReportData(
            self.CONSENSUS_VERSION,
            blockstamp.ref_slot,
            len(validators),
            data_format,
            data,
        )

        EJECTOR_VALIDATORS_COUNT_TO_EJECT.set(report_data.requests_count)

        return report_data.as_tuple()

    def get_validators_to_eject(self, blockstamp: ReferenceBlockStamp) -> list[tuple[NodeOperatorGlobalIndex, LidoValidator]]:
        to_withdraw_amount = self.get_total_unfinalized_withdrawal_requests_amount(blockstamp)
        logger.info({'msg': 'Calculate to withdraw amount.', 'value': to_withdraw_amount})

        EJECTOR_TO_WITHDRAW_WEI_AMOUNT.set(to_withdraw_amount)

        if to_withdraw_amount == Wei(0):
            return []

        chain_config = self.get_chain_config(blockstamp)

        rewards_speed_per_epoch = self.prediction_service.get_rewards_per_epoch(blockstamp, chain_config)
        logger.info({'msg': 'Calculate average rewards speed per epoch.', 'value': rewards_speed_per_epoch})

        epochs_to_sweep = self._get_sweep_delay_in_epochs(blockstamp)
        logger.info({'msg': 'Calculate epochs to sweep.', 'value': epochs_to_sweep})

        total_available_balance = self._get_total_el_balance(blockstamp)
        logger.info({'msg': 'Calculate available balance.', 'value': total_available_balance})

        validators_going_to_exit = self.validators_state_service.get_recently_requested_but_not_exited_validators(blockstamp, chain_config)
        going_to_withdraw_balance = sum(map(
            self._get_predicted_withdrawable_balance,
            validators_going_to_exit,
        ))
        logger.info({'msg': 'Calculate going to exit validators balance.', 'value': going_to_withdraw_balance})

        validators_to_eject: list[tuple[NodeOperatorGlobalIndex, LidoValidator]] = []
        validator_to_eject_balance_sum = 0

        validators_iterator = ExitOrderIterator(
            web3=self.w3,
            blockstamp=blockstamp,
            chain_config=chain_config
        )

        for validator_container in validators_iterator:
            withdrawal_epoch = self._get_predicted_withdrawable_epoch(blockstamp, len(validators_to_eject) + len(validators_going_to_exit) + 1)
            future_rewards = (withdrawal_epoch + epochs_to_sweep - blockstamp.ref_epoch) * rewards_speed_per_epoch

            future_withdrawals = self._get_withdrawable_lido_validators_balance(blockstamp, withdrawal_epoch)

            expected_balance = (
                future_withdrawals +  # Validators that have withdrawal_epoch
                future_rewards +  # Rewards we get until last validator in validators_to_eject will be withdrawn
                total_available_balance +  # Current EL balance (el vault, wc vault, buffered eth)
                validator_to_eject_balance_sum +  # Validators that we expected to be ejected (requested to exit, not delayed)
                going_to_withdraw_balance  # validators_to_eject balance
            )
            if expected_balance >= to_withdraw_amount:
                logger.info({
                    'msg': f'Expected withdrawal epoch: {withdrawal_epoch=}, '
                           f'will be reached in {withdrawal_epoch - blockstamp.ref_epoch} epochs. '
                           f'Validators with withdrawal_epoch before expected: {future_withdrawals=}. '
                           f'Future rewards from skimming and EL rewards: {future_rewards=}. '
                           f'Currently available balance: {total_available_balance=}. '
                           f'Validators expecting to start exit balance: {validator_to_eject_balance_sum=}. '
                           f'Validators going to eject balance: {going_to_withdraw_balance=}. ',
                    'withdrawal_epoch': withdrawal_epoch,
                    'ref_epoch': blockstamp.ref_epoch,
                    'future_withdrawals': future_withdrawals,
                    'future_rewards': future_rewards,
                    'total_available_balance': total_available_balance,
                    'validator_to_eject_balance_sum': validator_to_eject_balance_sum,
                    'going_to_withdraw_balance': going_to_withdraw_balance,
                })

                return validators_to_eject

            validators_to_eject.append(validator_container)
            (_, validator) = validator_container
            validator_to_eject_balance_sum += self._get_predicted_withdrawable_balance(validator)

        return validators_to_eject

    def _is_paused(self, blockstamp: ReferenceBlockStamp) -> bool:
        return self.report_contract.functions.isPaused().call(block_identifier=blockstamp.block_hash)

    def is_reporting_allowed(self, blockstamp: ReferenceBlockStamp) -> bool:
        on_pause = self._is_paused(blockstamp)
        CONTRACT_ON_PAUSE.set(on_pause)
        logger.info({'msg': 'Fetch isPaused from ejector bus contract.', 'value': on_pause})
        return not on_pause

    @lru_cache(maxsize=1)
    def _get_withdrawable_lido_validators_balance(self, blockstamp: BlockStamp, on_epoch: EpochNumber) -> Wei:
        lido_validators = self.w3.lido_validators.get_lido_validators(blockstamp=blockstamp)

        def get_total_withdrawable_balance(balance: Wei, validator: Validator) -> Wei:
            if is_fully_withdrawable_validator(validator, on_epoch):
                balance = Wei(
                    balance + self._get_predicted_withdrawable_balance(validator)
                )

            return balance

        result = reduce(
            get_total_withdrawable_balance,
            lido_validators,
            Wei(0),
        )

        return result

    def _get_predicted_withdrawable_balance(self, validator: Validator) -> Wei:
        return self.w3.to_wei(min(int(validator.balance), MAX_EFFECTIVE_BALANCE), 'gwei')

    def _get_total_el_balance(self, blockstamp: BlockStamp) -> Wei:
        total_el_balance = Wei(
            self.w3.lido_contracts.get_el_vault_balance(blockstamp) +
            self.w3.lido_contracts.get_withdrawal_balance(blockstamp) +
            self._get_buffer_ether(blockstamp)
        )
        logger.info({'msg': 'Calculate total el balance.', 'value': total_el_balance})
        return total_el_balance

    def _get_buffer_ether(self, blockstamp: BlockStamp) -> Wei:
        """
        The reserved buffered ether is min(current_buffered_ether, unfinalized_withdrawal_requests_amount)
        We can skip calculating reserved buffer for ejector, because in case if
        (unfinalized_withdrawal_requests_amount <= current_buffered_ether)
        We won't eject validators at all, because we have enough eth to fulfill all requests.
        """
        return Wei(
            self.w3.lido_contracts.lido.functions.getBufferedEther().call(
                block_identifier=blockstamp.block_hash
            )
        )

    def get_total_unfinalized_withdrawal_requests_amount(self, blockstamp: BlockStamp) -> Wei:
        unfinalized_steth = self.w3.lido_contracts.withdrawal_queue_nft.functions.unfinalizedStETH().call(
            block_identifier=blockstamp.block_hash,
        )
        logger.info({'msg': 'Wei to finalize.', 'value': unfinalized_steth})
        return unfinalized_steth

    def _get_predicted_withdrawable_epoch(
        self,
        blockstamp: ReferenceBlockStamp,
        validators_to_eject_count: int,
    ) -> EpochNumber:
        """
        Returns epoch when all validators in queue and validators_to_eject will be withdrawn.
        """
        max_exit_epoch_number, latest_to_exit_validators_count = self._get_latest_exit_epoch(blockstamp)

        max_exit_epoch_number = max(
            max_exit_epoch_number,
            self.compute_activation_exit_epoch(blockstamp),
        )

        EJECTOR_MAX_EXIT_EPOCH.set(max_exit_epoch_number)

        churn_limit = self._get_churn_limit(blockstamp)

        remain_exits_capacity_for_epoch = churn_limit - latest_to_exit_validators_count
        epochs_required_to_exit_validators = (validators_to_eject_count - remain_exits_capacity_for_epoch) // churn_limit + 1

        return EpochNumber(max_exit_epoch_number + epochs_required_to_exit_validators + MIN_VALIDATOR_WITHDRAWABILITY_DELAY)

    @staticmethod
    def compute_activation_exit_epoch(blockstamp: ReferenceBlockStamp):
        """
        Return the epoch during which validator activations and exits initiated in ``epoch`` take effect.

        Spec: https://github.com/LeastAuthority/eth2.0-specs/blob/dev/specs/phase0/beacon-chain.md#compute_activation_exit_epoch
        """
        return blockstamp.ref_epoch + 1 + MAX_SEED_LOOKAHEAD

    @lru_cache(maxsize=1)
    def _get_latest_exit_epoch(self, blockstamp: BlockStamp) -> tuple[EpochNumber, int]:
        """
        Returns the latest exit epoch and amount of validators that are exiting in this epoch
        """
        max_exit_epoch_number = EpochNumber(0)
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
        full_sweep_in_epochs = total_withdrawable_validators / MAX_WITHDRAWALS_PER_PAYLOAD / chain_config.slots_per_epoch
        return int(full_sweep_in_epochs * self.AVG_EXPECTING_WITHDRAWALS_SWEEP_DURATION_MULTIPLIER)

    @lru_cache(maxsize=1)
    def _get_churn_limit(self, blockstamp: ReferenceBlockStamp) -> int:
        total_active_validators = reduce(
            lambda total, validator: total + int(is_active_validator(validator, blockstamp.ref_epoch)),
            self.w3.cc.get_validators(blockstamp),
            0,
        )
        return max(MIN_PER_EPOCH_CHURN_LIMIT, total_active_validators // CHURN_LIMIT_QUOTIENT)

    def _get_processing_state(self, blockstamp: BlockStamp) -> EjectorProcessingState:
        ps = named_tuple_to_dataclass(
            self.report_contract.functions.getProcessingState().call(block_identifier=blockstamp.block_hash),
            EjectorProcessingState,
        )
        logger.info({'msg': 'Fetch processing state.', 'value': ps})
        return ps

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        processing_state = self._get_processing_state(blockstamp)
        return processing_state.data_submitted

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        return not self.is_main_data_submitted(blockstamp)
