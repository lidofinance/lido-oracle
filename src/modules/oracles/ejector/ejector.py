import dataclasses
import logging
from typing import cast

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
from src.modules.common.types import ZERO_HASH, ModuleExecuteDelay
from src.modules.oracles.common.consensus import InitialEpochIsYetToArriveRevert
from src.modules.oracles.common.oracle_module import OracleModule
from src.modules.oracles.ejector.data_encode import encode_data
from src.modules.oracles.ejector.sweep import get_sweep_delay_in_epochs
from src.modules.oracles.ejector.types import EjectorProcessingState, ReportData
from src.providers.consensus.types import BeaconStateView, Validator
from src.providers.execution.contracts.exit_bus_oracle import ExitBusOracleContract
from src.providers.execution.contracts.hash_consensus import HashConsensusContract
from src.services.exit_order_iterator import ValidatorExitIterator
from src.services.prediction import RewardsPredictionService
from src.services.validator_state import LidoValidatorStateService
from src.types import BlockStamp, EpochNumber, Gwei, NodeOperatorGlobalIndex, ReferenceBlockStamp
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.units import gwei_to_wei
from src.utils.validator_balance import get_predictable_balance, get_predictable_full_balance, get_predictable_sweep
from src.utils.validator_state import (
    compute_activation_exit_epoch,
    get_activation_exit_churn_limit,
    is_active_validator,
    is_fully_withdrawable_validator,
)
from src.web3py.extensions.lido_validators import LidoValidator
from src.web3py.types import Web3


logger = logging.getLogger(__name__)


class Ejector(OracleModule[Web3]):
    """
    The module that requests that Lido validators exit so that unfinalized Withdrawal Requests (WR)
    are closed as quickly as possible, without triggering unnecessary additional withdrawals.

    Flow:
    1. Fetch ETH amount required to cover unfinalized WR.
    2. Calculate ETH rewards prediction per epoch.

    Loop:
        1. Calculate the withdrawal epoch for the last validator in the "to eject" list.
        2. Calculate the predicted rewards that will be received until the last validator is withdrawn.
        3. Check whether the sum of the following components will be enough to cover all WR:
            - Exiting validators’ balances
            - Validators’ balances in the "to eject" list
            - Predicted rewards
            - Predicted validator top-ups
            - Current balance on EL
        4. If the sum is already enough to cover WR, exit the loop.
        5. Get the next validator to eject.

    3. Decode lido validators into bytes and send report transaction
    """

    COMPATIBLE_CONTRACT_VERSION = 3
    COMPATIBLE_CONSENSUS_VERSION = 5

    def __init__(self, w3: Web3):
        self.report_contract: ExitBusOracleContract = w3.lido_contracts.validators_exit_bus_oracle

        super().__init__(w3)

        self.prediction_service = RewardsPredictionService(w3)
        self.validators_state_service = LidoValidatorStateService(w3)

    def refresh_contracts(self):
        self.report_contract = self.w3.lido_contracts.validators_exit_bus_oracle  # type: ignore

    def is_contracts_addresses_changed(self) -> bool:
        return self.w3.lido_contracts.has_contract_address_changed()

    def is_reporting_allowed(self, blockstamp: ReferenceBlockStamp) -> bool:
        on_pause = self.report_contract.is_paused('latest')
        CONTRACT_ON_PAUSE.labels('vebo').set(on_pause)
        logger.info({'msg': 'Fetch isPaused from ejector bus contract.', 'value': on_pause})
        return not on_pause

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

    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        report_blockstamp = self.get_blockstamp_for_report(last_finalized_blockstamp)

        if not report_blockstamp or not self._check_compatibility(report_blockstamp):
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        self.process_report(report_blockstamp)
        return ModuleExecuteDelay.NEXT_SLOT

    @lru_cache(maxsize=1)
    @duration_meter()
    def build_report(self, blockstamp: ReferenceBlockStamp) -> tuple:
        # For metrics only
        self.w3.lido_contracts.get_ejector_last_processing_ref_slot(blockstamp)

        validators: list[tuple[NodeOperatorGlobalIndex, LidoValidator]] = self.get_validators_to_eject(blockstamp)
        logger.info(
            {
                'msg': f'Calculate validators to eject. Count: {len(validators)}',
                'value': [val[1].index for val in validators],
            },
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

    def get_validators_to_eject(
        self, blockstamp: ReferenceBlockStamp
    ) -> list[tuple[NodeOperatorGlobalIndex, LidoValidator]]:
        to_withdraw_amount = self.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth(blockstamp.block_hash)
        EJECTOR_TO_WITHDRAW_WEI_AMOUNT.set(to_withdraw_amount)

        # Get all balance available to use to fulfill on closes exit epoch
        predictable_el_balance = self._get_predicted_el_balance(Gwei(0), blockstamp)

        validators_to_eject: list[tuple[NodeOperatorGlobalIndex, LidoValidator]] = []
        total_balance_to_eject_gwei = Gwei(0)
        validators_iterator = iter(
            ValidatorExitIterator(
                w3=self.w3,
                blockstamp=blockstamp,
                chain_config=self.get_chain_config(blockstamp),
            )
        )

        if to_withdraw_amount != 0 and to_withdraw_amount > predictable_el_balance:
            for gid, next_validator in validators_iterator:
                validators_to_eject.append((gid, next_validator))

                val_balance = get_predictable_balance(next_validator)

                total_balance_to_eject_gwei += val_balance

                predictable_el_balance = self._get_predicted_el_balance(total_balance_to_eject_gwei, blockstamp)

                if predictable_el_balance + gwei_to_wei(total_balance_to_eject_gwei) > to_withdraw_amount:
                    break
        else:
            logger.info({'msg': 'Predicted EL balance is enough to fulfill withdrawal queue.'})

        forced_validators = validators_iterator.get_remaining_forced_validators()
        if forced_validators:
            logger.info({'msg': 'Eject forced to exit validators.', 'len': len(forced_validators)})
            validators_to_eject.extend(forced_validators)

        logger.info(
            {
                'msg': 'Calculate validators to eject',
                'total_balance_to_eject': gwei_to_wei(total_balance_to_eject_gwei),
                'predictable_el_balance': predictable_el_balance,
                'validators_to_eject_count': len(validators_to_eject),
            }
        )

        return validators_to_eject

    def _get_predicted_el_balance(self, to_exit_gwei: Gwei, blockstamp: ReferenceBlockStamp) -> Wei:
        chain_config = self.get_chain_config(blockstamp)

        total_available_balance = self._get_total_el_balance(blockstamp)
        logger.info({'msg': 'Calculate el balance.', 'value': total_available_balance})

        epochs_to_sweep = self._get_sweep_delay_in_epochs(blockstamp)
        logger.info({'msg': 'Calculate epochs to sweep.', 'value': epochs_to_sweep})

        rewards_speed_per_epoch = self.prediction_service.get_rewards_per_epoch(blockstamp, chain_config)
        logger.info({'msg': 'Calculate average rewards speed per epoch.', 'value': rewards_speed_per_epoch})

        validators_going_to_exit = self.validators_state_service.get_recently_requested_but_not_exiting_validators(
            chain_config,
            blockstamp,
        )

        going_to_withdraw_balance_gwei = Gwei(
            sum(
                map(
                    get_predictable_full_balance,
                    validators_going_to_exit,
                ),
                Gwei(0),
            )
        )

        withdrawal_epoch = self._get_predicted_withdrawable_epoch(
            going_to_withdraw_balance_gwei + to_exit_gwei,
            blockstamp,
        )
        logger.info({'msg': 'Withdrawal epoch', 'value': withdrawal_epoch})
        EJECTOR_MAX_WITHDRAWAL_EPOCH.set(withdrawal_epoch)

        time_to_last_withdrawal_in_epoch = withdrawal_epoch + epochs_to_sweep - blockstamp.ref_epoch

        future_rewards = time_to_last_withdrawal_in_epoch * rewards_speed_per_epoch
        logger.info({'msg': 'Calculate future rewards.', 'value': future_rewards})

        future_withdrawals = self._get_withdrawable_lido_validators_balance(withdrawal_epoch, blockstamp)
        logger.info({'msg': 'Calculate future withdrawals sum.', 'value': future_withdrawals})

        deposit_lock = self._get_deposit_lock_amount(time_to_last_withdrawal_in_epoch, blockstamp)
        logger.info({'msg': 'Calculate deposit lock.', 'value': deposit_lock})

        return Wei(
            future_rewards
            + future_withdrawals
            + total_available_balance
            + gwei_to_wei(going_to_withdraw_balance_gwei)
            - deposit_lock,
        )

    @lru_cache(maxsize=1)
    def _get_withdrawable_lido_validators_balance(self, on_epoch: EpochNumber, blockstamp: BlockStamp) -> Wei:
        lido_validators = self.w3.lido_validators.get_active_lido_validators(blockstamp=blockstamp)

        result = Gwei(0)

        for v in lido_validators:
            if v.consolidating_as_source:
                continue

            if is_fully_withdrawable_validator(v.validator, v.balance, on_epoch):
                result += get_predictable_full_balance(v)
            else:
                result += get_predictable_sweep(v)

        return gwei_to_wei(result)

    @lru_cache(maxsize=1)
    def _get_total_el_balance(self, blockstamp: BlockStamp) -> Wei:
        return Wei(
            self.w3.lido_contracts.get_el_vault_balance(blockstamp)
            + self.w3.lido_contracts.get_withdrawal_balance(blockstamp)
            + self.w3.lido_contracts.lido.get_withdrawals_reserve(blockstamp.block_hash)
        )

    def _get_predicted_withdrawable_epoch(
        self,
        exiting_balance_sum: Gwei,
        blockstamp: ReferenceBlockStamp,
    ) -> EpochNumber:
        state = self.w3.cc.get_state_view(blockstamp)
        earliest_exit_epoch = self.compute_exit_epoch_and_update_churn(
            state,
            exiting_balance_sum,
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
        """Returns the number of epochs that will take to sweep all validators in the chain."""
        chain_config = self.get_chain_config(blockstamp)
        state = self.w3.cc.get_state_view(blockstamp)
        return get_sweep_delay_in_epochs(state, chain_config)

    # https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#get_total_active_balance
    def _get_total_active_balance(self, blockstamp: ReferenceBlockStamp) -> Gwei:
        active_validators = self._get_active_validators(blockstamp)
        return max(
            EFFECTIVE_BALANCE_INCREMENT, sum((v.validator.effective_balance for v in active_validators), Gwei(0))
        )

    @lru_cache(maxsize=1)
    def _get_active_validators(self, blockstamp: ReferenceBlockStamp) -> list[Validator]:
        return [v for v in self.w3.cc.get_validators(blockstamp) if is_active_validator(v, blockstamp.ref_epoch)]

    def _get_deposit_lock_amount(self, epoches_number: int, blockstamp: ReferenceBlockStamp) -> Wei:
        """
        Calculates the amount of ETH locked for depositing for a given epoches_number.
        """
        deposit_per_frame = self.w3.lido_contracts.lido.get_deposits_reserve_target(blockstamp.block_hash)
        max_wr_wei = self.w3.lido_contracts.withdrawal_queue_nft.max_steth_withdrawal_amount(blockstamp.block_hash)

        # Withdrawn ETH lands in the Withdrawal Vault or EL rewards vault and only reaches
        # the buffer after WRs are fulfilled — so it cannot be redirected to deposits unless
        # the first WR in line exceeds the available buffer. In that worst case, at most `max_wr_wei` per
        # frame can flow into the buffer for deposits instead of fulfilling withdrawals
        reserve_per_frame = min(deposit_per_frame, max_wr_wei)

        consensus_contract = cast(
            HashConsensusContract,
            self.w3.eth.contract(
                address=self.w3.lido_contracts.accounting_oracle.get_consensus_contract(blockstamp.block_hash),
                ContractFactoryClass=HashConsensusContract,
                decode_tuples=True,
            ),
        )

        ao_frame_size = consensus_contract.get_frame_config(blockstamp.block_hash).epochs_per_frame
        # `get_withdrawals_reserve` already reflects the reserve locked for the current accounting
        # frame at `blockstamp`. Only additional fully covered accounting frames within
        # `epoches_number` must be added here, so floor-division is intentional. Using ceil
        # would over-count by adding a reserve for a partial / already-accounted frame.
        ao_frames = epoches_number // ao_frame_size

        return Wei(ao_frames * reserve_per_frame)
