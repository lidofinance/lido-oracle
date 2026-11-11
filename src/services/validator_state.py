import logging
from collections import defaultdict
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from functools import reduce

from src.constants import MIN_ACTIVATION_BALANCE
from src.metrics.prometheus.accounting import ACCOUNTING_EXITED_VALIDATORS
from src.providers.execution.withdrawal_request_queue import get_queued_withdrawal_requests
from src.types import EpochNumber, Gwei, OperatorsValidatorCount, ReferenceBlockStamp, ValidatorIndex
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.validator_state import is_exited_validator, is_on_exit
from src.web3py.extensions.lido_validators import LidoValidator
from src.web3py.types import Web3


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InFlightWithdrawals:
    """Withdrawals requested in earlier reports and not finished yet, by validator index."""

    pwr_amounts: dict[ValidatorIndex, Gwei] = field(default_factory=dict)
    fwr_validators: frozenset[ValidatorIndex] = frozenset()
    # The part of `pwr_amounts` already on the CL, and the latest epoch it becomes withdrawable.
    cl_pending_pwr_amounts: dict[ValidatorIndex, Gwei] = field(default_factory=dict)
    cl_pending_withdrawable_epochs: dict[ValidatorIndex, EpochNumber] = field(default_factory=dict)


@dataclass(frozen=True)
class InFlightInbound:
    """ETH that withdrawals requested in earlier reports bring to the EL, each validator counted once."""

    amount: Gwei = Gwei(0)
    # Requests still in the EIP-7002 queue or the Bus: they take exit churn before the requests of this report.
    queued_churn: Gwei = Gwei(0)
    latest_cl_withdrawable_epoch: EpochNumber | None = None


def get_in_flight_inbound(validators: Iterable[LidoValidator], in_flight: InFlightWithdrawals) -> InFlightInbound:
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

        cl_pending = in_flight.cl_pending_pwr_amounts.get(validator.index, Gwei(0))
        # The CL skips a full exit request while the validator has pending partials.
        if validator.index in in_flight.fwr_validators and not cl_pending:
            amount = Gwei(amount + validator.balance)
            queued_churn = Gwei(queued_churn + validator.validator.effective_balance)
            continue

        # The CL applies partials one by one against the balance left above the activation balance.
        pwr_amount = min(
            in_flight.pwr_amounts.get(validator.index, Gwei(0)),
            Gwei(max(0, validator.balance - MIN_ACTIVATION_BALANCE)),
        )
        amount = Gwei(amount + pwr_amount)
        queued_churn = Gwei(queued_churn + max(0, pwr_amount - cl_pending))
        if cl_pending:
            withdrawable_epochs.append(in_flight.cl_pending_withdrawable_epochs[validator.index])

    return InFlightInbound(
        amount=amount,
        queued_churn=queued_churn,
        latest_cl_withdrawable_epoch=max(withdrawable_epochs, default=None),
    )


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
        PWRs pending on the CL, Lido requests queued in the EIP-7002 system contract,
        and intents queued in the TriggerableWithdrawalsBus.
        """
        pwr_amounts: dict[ValidatorIndex, Gwei] = defaultdict(lambda: Gwei(0))
        fwr_validators: set[ValidatorIndex] = set()
        cl_pending_amounts: dict[ValidatorIndex, Gwei] = defaultdict(lambda: Gwei(0))
        cl_pending_epochs: dict[ValidatorIndex, EpochNumber] = {}

        state = self.w3.cc.get_state_view(blockstamp)
        for pending in state.pending_partial_withdrawals:
            index = ValidatorIndex(pending.validator_index)
            pwr_amounts[index] += pending.amount
            cl_pending_amounts[index] += pending.amount
            cl_pending_epochs[index] = max(cl_pending_epochs.get(index, EpochNumber(0)), pending.withdrawable_epoch)

        withdrawal_vault = self.w3.lido_contracts.lido_locator.withdrawal_vault(blockstamp.block_hash)
        queued = [
            request
            for request in get_queued_withdrawal_requests(self.w3, blockstamp.block_hash)
            if request.source_address == withdrawal_vault
        ]
        intents = self.w3.lido_contracts.triggerable_withdrawals_bus.get_unprocessed_intents(blockstamp.block_hash)

        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)
        index_by_pubkey = {v.validator.pubkey: v.index for vs in lido_validators.values() for v in vs}
        for request in [*queued, *intents]:
            index = index_by_pubkey.get(request.pubkey)
            if index is None:
                logger.warning({'msg': 'Queued withdrawal request for an unknown validator.', 'pubkey': request.pubkey})
                continue
            if request.is_full:
                fwr_validators.add(index)
            else:
                pwr_amounts[index] += request.amount

        return InFlightWithdrawals(
            pwr_amounts=dict(pwr_amounts),
            fwr_validators=frozenset(fwr_validators),
            cl_pending_pwr_amounts=dict(cl_pending_amounts),
            cl_pending_withdrawable_epochs=cl_pending_epochs,
        )

    def get_in_flight_inbound(self, blockstamp: ReferenceBlockStamp) -> InFlightInbound:
        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)
        return get_in_flight_inbound(
            (validator for validators in lido_validators.values() for validator in validators),
            self.get_in_flight_withdrawals(blockstamp),
        )
