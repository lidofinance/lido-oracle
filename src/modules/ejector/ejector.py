import dataclasses
import logging

from web3.exceptions import ContractCustomError
from web3.types import Wei

from src.constants import (
    EFFECTIVE_BALANCE_INCREMENT,
    MIN_VALIDATOR_WITHDRAWABILITY_DELAY,
)
from src.metrics.prometheus.business import CONTRACT_ON_PAUSE
from src.metrics.prometheus.duration_meter import duration_meter
from src.metrics.prometheus.ejector import (
    EJECTOR_MAX_WITHDRAWAL_EPOCH,
    EJECTOR_TO_WITHDRAW_WEI_AMOUNT,
    EJECTOR_VALIDATORS_COUNT_TO_EJECT,
)
from src.modules.ejector.data_encode import encode_data
from src.modules.ejector.sweep import get_sweep_delay_in_epochs
from src.modules.ejector.types import EjectorProcessingState, ReportData
from src.modules.submodules.consensus import ConsensusModule, InitialEpochIsYetToArriveRevert
from src.modules.submodules.oracle_module import BaseModule, ModuleExecuteDelay
from src.modules.submodules.types import ZERO_HASH
from src.providers.consensus.types import Validator, BeaconStateView
from src.providers.execution.contracts.exit_bus_oracle import ExitBusOracleContract
from src.services.exit_order_iterator import ValidatorExitIterator
from src.services.prediction import RewardsPredictionService
from src.services.validator_state import LidoValidatorStateService
from src.types import BlockStamp, EpochNumber, Gwei, NodeOperatorGlobalIndex, ReferenceBlockStamp
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.units import gwei_to_wei
from src.utils.validator_state import (
    compute_activation_exit_epoch,
    get_activation_exit_churn_limit,
    get_max_effective_balance,
    is_active_validator,
    is_fully_withdrawable_validator,
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

    COMPATIBLE_CONTRACT_VERSION = 2
    COMPATIBLE_CONSENSUS_VERSION = 4

    def __init__(self, w3: Web3):
        self.report_contract: ExitBusOracleContract = w3.lido_contracts.validators_exit_bus_oracle

        super().__init__(w3)

        self.prediction_service = RewardsPredictionService(w3)
        self.validators_state_service = LidoValidatorStateService(w3)

    def refresh_contracts(self):
        self.report_contract = self.w3.lido_contracts.validators_exit_bus_oracle  # type: ignore

    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        report_blockstamp = self.get_blockstamp_for_report(last_finalized_blockstamp)

        if not report_blockstamp or not self._check_compatability(report_blockstamp):
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
            consensus_version=self.get_consensus_version(blockstamp),
            ref_slot=blockstamp.ref_slot,
            requests_count=len(validators),
            data_format=data_format,
            data=data,
        )

        EJECTOR_VALIDATORS_COUNT_TO_EJECT.set(report_data.requests_count)

        return dataclasses.astuple(report_data)

    def get_validators_to_eject(self, blockstamp: ReferenceBlockStamp) -> list[tuple[NodeOperatorGlobalIndex, LidoValidator]]:
        to_withdraw_amount = self.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth(blockstamp.block_hash)
        EJECTOR_TO_WITHDRAW_WEI_AMOUNT.set(to_withdraw_amount)
        logger.info({'msg': 'Calculate to withdraw amount.', 'value': to_withdraw_amount})

        expected_balance = self._get_total_expected_balance([], blockstamp)

        chain_config = self.get_chain_config(blockstamp)
        validators_iterator = iter(ValidatorExitIterator(
            w3=self.w3,
            blockstamp=blockstamp,
            chain_config=chain_config,
        ))

        validators_to_eject: list[tuple[NodeOperatorGlobalIndex, LidoValidator]] = []
        total_balance_to_eject_wei = 0

        try:
            while expected_balance < to_withdraw_amount:
                gid, next_validator = next(validators_iterator)
                validators_to_eject.append((gid, next_validator))
                total_balance_to_eject_wei += self._get_predicted_withdrawable_balance(next_validator)
                expected_balance = Wei(
                    self._get_total_expected_balance([v for (_, v) in validators_to_eject], blockstamp)
                    + total_balance_to_eject_wei
                )
        except StopIteration:
            pass

        logger.info({
            'msg': 'Calculate validators to eject',
            'expected_balance': expected_balance,
            'to_withdraw_amount': to_withdraw_amount,
            'validators_to_eject_count': len(validators_to_eject),
        })

        forced_validators = validators_iterator.get_remaining_forced_validators()
        if forced_validators:
            logger.info({'msg': 'Eject forced to exit validators.', 'len': len(forced_validators)})
            validators_to_eject.extend(forced_validators)

        return validators_to_eject

    def _get_total_expected_balance(self, vals_to_exit: list[Validator], blockstamp: ReferenceBlockStamp) -> Wei:
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

        withdrawal_epoch = self._get_predicted_withdrawable_epoch(blockstamp, validators_going_to_exit + vals_to_exit)
        logger.info({'msg': 'Withdrawal epoch', 'value': withdrawal_epoch})
        EJECTOR_MAX_WITHDRAWAL_EPOCH.set(withdrawal_epoch)

        future_withdrawals = self._get_withdrawable_lido_validators_balance(withdrawal_epoch, blockstamp)
        logger.info({'msg': 'Calculate future withdrawals sum.', 'value': future_withdrawals})
        future_rewards = (withdrawal_epoch + epochs_to_sweep - blockstamp.ref_epoch) * rewards_speed_per_epoch
        logger.info({'msg': 'Calculate future rewards.', 'value': future_rewards})

        total_available_balance = self._get_total_el_balance(blockstamp)
        logger.info({'msg': 'Calculate el balance.', 'value': total_available_balance})

        return Wei(future_rewards + future_withdrawals + total_available_balance + going_to_withdraw_balance)

    def is_reporting_allowed(self, blockstamp: ReferenceBlockStamp) -> bool:
        on_pause = self.report_contract.is_paused('latest')
        CONTRACT_ON_PAUSE.labels('vebo').set(on_pause)
        logger.info({'msg': 'Fetch isPaused from ejector bus contract.', 'value': on_pause})
        return not on_pause

    @lru_cache(maxsize=1)
    def _get_withdrawable_lido_validators_balance(self, on_epoch: EpochNumber, blockstamp: BlockStamp) -> Wei:
        lido_validators = self.w3.lido_validators.get_lido_validators(blockstamp=blockstamp)
        return sum(
            (
                self._get_predicted_withdrawable_balance(v)
                for v in lido_validators
                if is_fully_withdrawable_validator(v.validator, v.balance, on_epoch)
            ),
            Wei(0),
        )

    def _get_predicted_withdrawable_balance(self, validator: Validator) -> Wei:
        return gwei_to_wei(min(validator.balance, get_max_effective_balance(validator.validator)))

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
        validators_to_eject: list[Validator],
    ) -> EpochNumber:
        state = self.w3.cc.get_state_view(blockstamp)
        earliest_exit_epoch = self.compute_exit_epoch_and_update_churn(
            state,
            Gwei(sum(int(v.validator.effective_balance) for v in validators_to_eject)),
            blockstamp,
        )
        return EpochNumber(earliest_exit_epoch + MIN_VALIDATOR_WITHDRAWABILITY_DELAY)

    def compute_exit_epoch_and_update_churn(
        self,
        state: BeaconStateView,
        exit_balance: Gwei,
        blockstamp: ReferenceBlockStamp,
    ) -> EpochNumber:
        """
        https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#new-compute_exit_epoch_and_update_churn
        """
        earliest_exit_epoch = max(state.earliest_exit_epoch, compute_activation_exit_epoch(blockstamp.ref_epoch))
        per_epoch_churn = get_activation_exit_churn_limit(self._get_total_active_balance(blockstamp))
        # New epoch for exits.
        if state.earliest_exit_epoch < earliest_exit_epoch:
            exit_balance_to_consume = per_epoch_churn
        else:
            exit_balance_to_consume = state.exit_balance_to_consume

        # Exit doesn't fit in the current earliest epoch.
        if exit_balance > exit_balance_to_consume:
            balance_to_process = exit_balance - exit_balance_to_consume
            additional_epochs = (balance_to_process - 1) // per_epoch_churn + 1
            earliest_exit_epoch += additional_epochs

        return EpochNumber(earliest_exit_epoch)

    @lru_cache(maxsize=1)
    def _get_sweep_delay_in_epochs(self, blockstamp: ReferenceBlockStamp) -> int:
        """Returns amount of epochs that will take to sweep all validators in chain."""
        chain_config = self.get_chain_config(blockstamp)
        state = self.w3.cc.get_state_view(blockstamp)
        return get_sweep_delay_in_epochs(state, chain_config)

    # https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#get_total_active_balance
    def _get_total_active_balance(self, blockstamp: ReferenceBlockStamp) -> Gwei:
        active_validators = self._get_active_validators(blockstamp)
        return max(EFFECTIVE_BALANCE_INCREMENT, sum((v.validator.effective_balance for v in active_validators), Gwei(0)))

    @lru_cache(maxsize=1)
    def _get_active_validators(self, blockstamp: ReferenceBlockStamp) -> list[Validator]:
        return [v for v in self.w3.cc.get_validators(blockstamp) if is_active_validator(v, blockstamp.ref_epoch)]

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        processing_state = self._get_processing_state(blockstamp)
        return processing_state.data_submitted

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        return not self.is_main_data_submitted(blockstamp)

    def _get_processing_state(self, blockstamp: BlockStamp) -> EjectorProcessingState:
        try:
            return self.report_contract.get_processing_state(blockstamp.block_hash)
        except ContractCustomError as revert:
            if revert.data != InitialEpochIsYetToArriveRevert:
                raise revert

        frame = self.get_initial_or_current_frame(blockstamp)

        return EjectorProcessingState(
            current_frame_ref_slot=frame.ref_slot,
            processing_deadline_time=frame.report_processing_deadline_slot,
            data_hash=ZERO_HASH,
            data_submitted=False,
            data_format=0,
            requests_count=0,
            requests_submitted=0,
        )
