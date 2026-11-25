import logging
from collections import defaultdict
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from functools import reduce

from src.constants import (
    FAR_FUTURE_EPOCH,
    MAX_EFFECTIVE_BALANCE_ELECTRA,
    MIN_ACTIVATION_BALANCE,
    SHARD_COMMITTEE_PERIOD,
)
from src.metrics.prometheus.accounting import ACCOUNTING_EXITED_VALIDATORS
from src.providers.consensus.types import BeaconStateView
from src.providers.execution.withdrawal_request_queue import get_queued_withdrawal_requests
from src.types import EpochNumber, Gwei, OperatorsValidatorCount, ReferenceBlockStamp, ValidatorIndex
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.validator_state import has_compounding_withdrawal_credential, is_exited_validator, is_on_exit
from src.web3py.extensions.lido_validators import LidoValidator
from src.web3py.types import Web3


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InFlightWithdrawals:
    """Withdrawals requested in earlier reports and not finished yet, by validator index."""

    pwr_amounts: dict[ValidatorIndex, Gwei] = field(default_factory=dict)
    fwr_validators: frozenset[ValidatorIndex] = frozenset()
    # Queued FWRs behind a queued PWR of the same validator: the PWR becomes a CL pending partial first.
    fwr_after_pwr_validators: frozenset[ValidatorIndex] = frozenset()
    # The part of `pwr_amounts` already on the CL, and the latest epoch it becomes withdrawable.
    cl_pending_pwr_amounts: dict[ValidatorIndex, Gwei] = field(default_factory=dict)
    cl_pending_withdrawable_epochs: dict[ValidatorIndex, EpochNumber] = field(default_factory=dict)
    # The part of `pwr_amounts` the CL already took off the balance for the next execution payload (Gloas).
    payload_pwr_amounts: dict[ValidatorIndex, Gwei] = field(default_factory=dict)


@dataclass(frozen=True)
class InFlightInbound:
    """ETH that withdrawals requested in earlier reports bring to the EL, each validator counted once."""

    amount: Gwei = Gwei(0)
    # Requests still in the EIP-7002 queue or the Bus: they take exit churn before the requests of this report.
    queued_churn: Gwei = Gwei(0)
    latest_cl_withdrawable_epoch: EpochNumber | None = None


def is_queued_fwr_effective(validator: LidoValidator, in_flight: InFlightWithdrawals, state_epoch: EpochNumber) -> bool:
    """
    Whether the CL exits the validator by its queued full withdrawal. The CL skips the request while the validator
    has pending partials, including those of PWRs queued ahead of it, and drops it for a validator active for less
    than SHARD_COMMITTEE_PERIOD. It processes the queues no earlier than `state_epoch`, the epoch of the state
    they are read at.
    """
    return (
        validator.index in in_flight.fwr_validators
        and validator.index not in in_flight.fwr_after_pwr_validators
        and not in_flight.cl_pending_pwr_amounts.get(validator.index)
        and validator.validator.activation_epoch + SHARD_COMMITTEE_PERIOD <= state_epoch
    )


def get_in_flight_inbound(
    validators: Iterable[LidoValidator], in_flight: InFlightWithdrawals, state_epoch: EpochNumber
) -> InFlightInbound:
    amount = Gwei(0)
    queued_churn = Gwei(0)
    withdrawable_epochs: list[EpochNumber] = []

    for validator in validators:
        # A consolidation source moves its balance to the target. A slashed validator becomes
        # withdrawable long after the horizon, and its final balance is not known yet.
        if validator.consolidating_as_source is not None or validator.validator.slashed:
            continue

        # The CL ignores new requests after the exit is initiated, and pays pending partials as 0.
        if is_on_exit(validator):
            amount = Gwei(amount + validator.balance)
            withdrawable_epochs.append(validator.validator.withdrawable_epoch)
            continue

        if is_queued_fwr_effective(validator, in_flight, state_epoch):
            amount = Gwei(amount + validator.balance)
            queued_churn = Gwei(queued_churn + validator.validator.effective_balance)
            continue

        # An ineffective queued FWR adds nothing.
        # The CL applies partials one by one against the balance left above the activation balance.
        cl_pending = in_flight.cl_pending_pwr_amounts.get(validator.index, Gwei(0))
        pwr_amount = min(
            in_flight.pwr_amounts.get(validator.index, Gwei(0)),
            Gwei(max(0, validator.balance - MIN_ACTIVATION_BALANCE)),
        )
        amount = Gwei(amount + pwr_amount)
        payload_pending = in_flight.payload_pwr_amounts.get(validator.index, Gwei(0))
        queued_churn = Gwei(queued_churn + max(0, pwr_amount - cl_pending - payload_pending))
        if cl_pending:
            withdrawable_epochs.append(in_flight.cl_pending_withdrawable_epochs[validator.index])

    return InFlightInbound(
        amount=amount,
        queued_churn=queued_churn,
        latest_cl_withdrawable_epoch=max(withdrawable_epochs, default=None),
    )


def get_payload_pwr_amounts(state: BeaconStateView, indexes: set[ValidatorIndex]) -> dict[ValidatorIndex, Gwei]:
    """
    Gloas: pending partials the CL already paid out of the balance, still owed by the next execution payload.

    The payload pays pending partials before the validator sweep, and a sweep skim leaves a compounding
    validator at exactly its max effective balance, so the last entry of such a validator is the skim.
    A full withdrawal needs an initiated exit, and the CL pays no partials then.
    """
    entries: defaultdict[ValidatorIndex, list[Gwei]] = defaultdict(list)
    for withdrawal in state.payload_expected_withdrawals:
        if withdrawal.validator_index in indexes:
            entries[ValidatorIndex(withdrawal.validator_index)].append(withdrawal.amount)

    amounts: dict[ValidatorIndex, Gwei] = {}
    for index, payouts in entries.items():
        validator = state.validators[index]
        if not has_compounding_withdrawal_credential(validator) or validator.exit_epoch != FAR_FUTURE_EPOCH:
            continue
        if state.balances[index] == MAX_EFFECTIVE_BALANCE_ELECTRA:
            payouts = payouts[:-1]
        if payouts:
            amounts[index] = Gwei(sum(payouts))
    return amounts


class LidoValidatorStateService:
    """Helper that calculates/aggregates Lido validator's states."""

    def __init__(self, w3: Web3):
        self.w3 = w3

    @lru_cache(maxsize=1)
    def get_lido_newly_exited_validators(self, blockstamp: ReferenceBlockStamp) -> OperatorsValidatorCount:
        lido_validators = deepcopy(self.get_exited_lido_validators(blockstamp))
        node_operators = self.w3.lido_validators.get_lido_node_operators(blockstamp)

        for operator in node_operators:
            global_index = (operator.staking_module.id, operator.id)
            ACCOUNTING_EXITED_VALIDATORS.labels(*global_index).set(lido_validators[global_index])
            # If number of exited validators weren't changed skip report for operator
            if lido_validators[global_index] == operator.total_exited_validators:
                del lido_validators[global_index]

        logger.info({'msg': 'Fetch new lido exited validators by node operator.', 'value': lido_validators})
        return lido_validators

    @lru_cache(maxsize=1)
    def get_exited_lido_validators(self, blockstamp: ReferenceBlockStamp) -> OperatorsValidatorCount:
        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)

        result = {}

        for global_no_index in lido_validators:
            result[global_no_index] = reduce(
                lambda total, validator: total + int(is_exited_validator(validator, blockstamp.ref_epoch)),
                lido_validators[global_no_index],
                0,
            )

        return result

    @lru_cache(maxsize=1)
    def get_in_flight_withdrawals(self, blockstamp: ReferenceBlockStamp) -> InFlightWithdrawals:
        """
        PWRs pending on the CL or its next execution payload, Lido requests queued in the EIP-7002 system contract,
        and intents queued in the TriggerableWithdrawalsBus.
        """
        pwr_amounts: dict[ValidatorIndex, Gwei] = defaultdict(lambda: Gwei(0))
        fwr_validators: set[ValidatorIndex] = set()
        fwr_after_pwr_validators: set[ValidatorIndex] = set()
        queued_pwr_validators: set[ValidatorIndex] = set()
        cl_pending_amounts: dict[ValidatorIndex, Gwei] = defaultdict(lambda: Gwei(0))
        cl_pending_epochs: dict[ValidatorIndex, EpochNumber] = {}

        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)
        index_by_pubkey = {v.validator.pubkey: v.index for vs in lido_validators.values() for v in vs}

        state = self.w3.cc.get_state_view(blockstamp)
        for pending in state.pending_partial_withdrawals:
            index = ValidatorIndex(pending.validator_index)
            pwr_amounts[index] += pending.amount
            cl_pending_amounts[index] += pending.amount
            cl_pending_epochs[index] = max(cl_pending_epochs.get(index, EpochNumber(0)), pending.withdrawable_epoch)

        payload_amounts = get_payload_pwr_amounts(state, set(index_by_pubkey.values()))
        for index, amount in payload_amounts.items():
            pwr_amounts[index] += amount

        withdrawal_vault = self.w3.lido_contracts.lido_locator.withdrawal_vault(blockstamp.block_hash)
        queued = [
            request
            for request in get_queued_withdrawal_requests(self.w3, blockstamp.block_hash)
            if request.source_address == withdrawal_vault
        ]
        intents = self.w3.lido_contracts.triggerable_withdrawals_bus.get_unprocessed_intents(blockstamp.block_hash)

        # The Bus sends its intents to the EIP-7002 queue, so the CL processes all of them in this order.
        for request in [*queued, *intents]:
            index = index_by_pubkey.get(request.pubkey)
            if index is None:
                logger.warning({'msg': 'Queued withdrawal request for an unknown validator.', 'pubkey': request.pubkey})
                continue
            if request.is_full:
                if index not in fwr_validators and index in queued_pwr_validators:
                    fwr_after_pwr_validators.add(index)
                fwr_validators.add(index)
            else:
                pwr_amounts[index] += request.amount
                queued_pwr_validators.add(index)

        return InFlightWithdrawals(
            pwr_amounts=dict(pwr_amounts),
            fwr_validators=frozenset(fwr_validators),
            fwr_after_pwr_validators=frozenset(fwr_after_pwr_validators),
            cl_pending_pwr_amounts=dict(cl_pending_amounts),
            cl_pending_withdrawable_epochs=cl_pending_epochs,
            payload_pwr_amounts=payload_amounts,
        )

    @lru_cache(maxsize=1)
    def get_in_flight_inbound(self, blockstamp: ReferenceBlockStamp) -> InFlightInbound:
        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)
        return get_in_flight_inbound(
            (validator for validators in lido_validators.values() for validator in validators),
            self.get_in_flight_withdrawals(blockstamp),
            blockstamp.epoch_number,
        )
