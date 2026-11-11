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
    EJECTOR_PARTIAL_WITHDRAWAL_GWEI_AMOUNT,
    EJECTOR_TO_WITHDRAW_WEI_AMOUNT,
    EJECTOR_VALIDATORS_COUNT_TO_EJECT,
    EJECTOR_WITHDRAWAL_REQUESTS,
)
from src.modules.common.types import ZERO_HASH, ModuleExecuteDelay
from src.modules.oracles.common.consensus import InitialEpochIsYetToArriveRevert
from src.modules.oracles.common.oracle_module import OracleModule
from src.modules.oracles.ejector.data_encode import WithdrawalRequest, encode_data
from src.modules.oracles.ejector.types import EjectorProcessingState, ReportData
from src.providers.consensus.types import BeaconStateView, Validator
from src.providers.execution.contracts.exit_bus_oracle import ExitBusOracleContract
from src.providers.execution.contracts.hash_consensus import HashConsensusContract
from src.services.exit_order_iterator import ValidatorExitIterator, WeightsNotUpdatedError
from src.services.prediction import RewardsPredictionService
from src.services.validator_state import InFlightInbound, LidoValidatorStateService
from src.types import BlockStamp, EpochNumber, Gwei, ReferenceBlockStamp
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.units import gwei_to_wei
from src.utils.validator_state import (
    compute_activation_exit_epoch,
    get_activation_exit_churn_limit,
    get_exit_churn_limit,
    get_max_effective_balance,
    has_execution_withdrawal_credential,
    is_active_validator,
)
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
        1. Calculate the epoch the last requested ETH arrives at, in-flight or in this report.
        2. Check whether the sum of the following components will be enough to cover all WR:
            - Current balance on EL
            - ETH requested in this report
            - ETH requested in earlier reports and not withdrawn yet
            - Rewards that reach the EL until that epoch
            - Minus the ETH we expect new deposits to consume over the same period
        3. If the sum is already enough to cover WR, exit the loop.
        4. Get the next withdrawal step.

    3. Decode lido validators into bytes and send report transaction
    """

    COMPATIBLE_CONTRACT_VERSION = 4
    COMPATIBLE_CONSENSUS_VERSION = 7

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
        )

    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        report_blockstamp = self.get_blockstamp_for_report(last_finalized_blockstamp)

        if not report_blockstamp or not self._check_compatibility(report_blockstamp):
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        try:
            self.process_report(report_blockstamp)
        except WeightsNotUpdatedError as error:
            logger.error(
                {'msg': 'Weights are not updated. Skipping report until next finalized epoch.', 'error': str(error)}
            )
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH
        return ModuleExecuteDelay.NEXT_SLOT

    @lru_cache(maxsize=1)
    @duration_meter()
    def build_report(self, blockstamp: ReferenceBlockStamp) -> tuple:
        # For metrics only
        self.w3.lido_contracts.get_ejector_last_processing_ref_slot(blockstamp)

        requests = self.get_withdrawal_requests(blockstamp)
        full = sum(r.is_full for r in requests)
        partial_amount = Gwei(sum(r.amount for r in requests))
        logger.info(
            {
                'msg': f'Calculate withdrawal requests. Count: {len(requests)}',
                'full': full,
                'partial': len(requests) - full,
                'partial_amount_gwei': partial_amount,
            },
        )

        report_data = ReportData(
            consensus_version=self.get_consensus_version(blockstamp),
            ref_slot=blockstamp.ref_slot,
            requests_count=len(requests),
            data=encode_data(
                requests,
                self.w3.lido_contracts.validators_exit_bus_oracle.get_max_requests_per_report(blockstamp.block_hash),
            ),
        )

        EJECTOR_VALIDATORS_COUNT_TO_EJECT.set(report_data.requests_count)
        EJECTOR_WITHDRAWAL_REQUESTS.labels(type='full').set(full)
        EJECTOR_WITHDRAWAL_REQUESTS.labels(type='partial').set(len(requests) - full)
        EJECTOR_PARTIAL_WITHDRAWAL_GWEI_AMOUNT.set(partial_amount)

        return dataclasses.astuple(report_data)

    def get_withdrawal_requests(self, blockstamp: ReferenceBlockStamp) -> list[WithdrawalRequest]:
        to_withdraw_amount = self.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth(blockstamp.block_hash)
        EJECTOR_TO_WITHDRAW_WEI_AMOUNT.set(to_withdraw_amount)

        # Get all balance available to use to fulfill on closes exit epoch
        predictable_el_balance = self._get_predicted_el_balance(Gwei(0), blockstamp)

        # ETH the requests of this report bring in: PWR amounts, and the balance of FWR validators.
        requested_gwei = Gwei(0)
        validators_iterator = iter(
            ValidatorExitIterator(
                w3=self.w3,
                blockstamp=blockstamp,
            )
        )

        # Phase 1: cover the WQ demand.
        if to_withdraw_amount != 0 and to_withdraw_amount > predictable_el_balance:
            for step in validators_iterator:
                requested_gwei = Gwei(requested_gwei + step.inbound)
                predictable_el_balance = self._get_predicted_el_balance(requested_gwei, blockstamp)

                if predictable_el_balance + gwei_to_wei(requested_gwei) >= to_withdraw_amount:
                    break
        else:
            logger.info({'msg': 'Predicted EL balance is enough to fulfill withdrawal queue.'})

        # Phase 2: forced exits not covered by Phase 1.
        forced_steps = validators_iterator.allocate_forced_exits()
        if forced_steps:
            logger.info({'msg': 'Request forced exits.', 'len': len(forced_steps)})

        # Phase 3: active rebalancing within CMv2.
        rebalancing_steps = validators_iterator.allocate_active_rebalancing()
        if rebalancing_steps:
            logger.info({'msg': 'Request active rebalancing withdrawals.', 'len': len(rebalancing_steps)})

        requests = validators_iterator.get_requests()

        logger.info(
            {
                'msg': 'Calculate withdrawal requests',
                'requested': gwei_to_wei(requested_gwei),
                'predictable_el_balance': predictable_el_balance,
                'requests_count': len(requests),
            }
        )

        return requests

    def _get_predicted_el_balance(self, to_exit_gwei: Gwei, blockstamp: ReferenceBlockStamp) -> Wei:
        el_balance = self._get_total_el_balance(blockstamp)
        in_flight = self.validators_state_service.get_in_flight_inbound(blockstamp)

        horizon_epoch = self._get_prediction_horizon(in_flight, to_exit_gwei, blockstamp)
        EJECTOR_MAX_WITHDRAWAL_EPOCH.set(horizon_epoch)
        epochs = horizon_epoch - blockstamp.ref_epoch

        liquid_rewards = self._get_liquid_rewards(epochs, blockstamp)
        deposit_lock = self._get_deposit_lock_amount(epochs, blockstamp)

        logger.info(
            {
                'msg': 'Calculate predicted EL balance.',
                'el_balance': el_balance,
                'in_flight': gwei_to_wei(in_flight.amount),
                'horizon_epoch': horizon_epoch,
                'liquid_rewards': liquid_rewards,
                'deposit_lock': deposit_lock,
            }
        )

        return Wei(el_balance + gwei_to_wei(in_flight.amount) + liquid_rewards - deposit_lock)

    def _get_prediction_horizon(
        self,
        in_flight: InFlightInbound,
        to_exit_gwei: Gwei,
        blockstamp: ReferenceBlockStamp,
    ) -> EpochNumber:
        """
        The latest epoch the requested ETH arrives at. Queued requests and the requests of this report
        take the exit churn in that order, so the last of them arrives with their sum. With nothing to
        churn, this is the earliest a new request could arrive.
        """
        horizon = self._get_predicted_withdrawable_epoch(Gwei(in_flight.queued_churn + to_exit_gwei), blockstamp)
        if in_flight.latest_cl_withdrawable_epoch is not None:
            horizon = max(horizon, in_flight.latest_cl_withdrawable_epoch)
        return horizon

    def _get_liquid_rewards(self, epochs: int, blockstamp: ReferenceBlockStamp) -> Wei:
        """EL rewards, and the CL rewards of the validators the CL sweep skims."""
        rewards = self.prediction_service.get_rewards_per_epoch(blockstamp, self.get_chain_config(blockstamp))
        lido_effective_balance, skimmed_effective_balance = self._get_lido_effective_balances(blockstamp)
        cl_rewards = 0
        if lido_effective_balance:
            cl_rewards = rewards.cl * skimmed_effective_balance * epochs // lido_effective_balance
        return Wei(rewards.el * epochs + cl_rewards)

    @lru_cache(maxsize=1)
    def _get_lido_effective_balances(self, blockstamp: ReferenceBlockStamp) -> tuple[Gwei, Gwei]:
        """Effective balance of all active Lido validators, and of those whose rewards the CL sweep skims."""
        total = Gwei(0)
        skimmed = Gwei(0)
        for v in self.w3.lido_validators.get_active_lido_validators(blockstamp):
            if not is_active_validator(v, blockstamp.ref_epoch):
                continue
            total = Gwei(total + v.validator.effective_balance)
            if has_execution_withdrawal_credential(v.validator) and v.validator.effective_balance == (
                get_max_effective_balance(v.validator)
            ):
                skimmed = Gwei(skimmed + v.validator.effective_balance)
        return total, skimmed

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
        https://github.com/ethereum/consensus-specs/blob/master/specs/electra/beacon-chain.md#new-compute_exit_epoch_and_update_churn
        """
        earliest_exit_epoch = max(state.earliest_exit_epoch, compute_activation_exit_epoch(blockstamp.ref_epoch))
        total_active_balance = self._get_total_active_balance(blockstamp)
        if self._is_gloas(blockstamp):
            # Post-EIP-8061 the capped limit overestimates withdrawal_epoch, which would make the
            # ejector under-request exits.
            per_epoch_churn = get_exit_churn_limit(total_active_balance)
        else:
            per_epoch_churn = get_activation_exit_churn_limit(total_active_balance)
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
    def _is_gloas(self, blockstamp: ReferenceBlockStamp) -> bool:
        """Resolved once per report: the fork gate is read for every exit candidate."""
        return self.w3.cc.is_gloas_epoch(blockstamp.epoch_number)

    # https://github.com/ethereum/consensus-specs/blob/master/specs/phase0/beacon-chain.md#get_total_active_balance
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
        ETH we expect new deposits to consume over `epoches_number`.

        Every accounting frame reserves `reserve_per_frame` for deposits, but new stake refills most
        of that reserve. `// 2` is the average case we expect deposits to actually take away from the
        ETH the withdrawal queue could otherwise use.
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

        return Wei(ao_frames * reserve_per_frame // 2)
