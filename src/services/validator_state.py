import logging
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from functools import reduce

from src.metrics.prometheus.accounting import ACCOUNTING_EXITED_VALIDATORS
from src.providers.execution.withdrawal_request_queue import get_queued_withdrawal_requests
from src.types import Gwei, OperatorsValidatorCount, ReferenceBlockStamp, ValidatorIndex
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

        state = self.w3.cc.get_state_view(blockstamp)
        for pending in state.pending_partial_withdrawals:
            pwr_amounts[ValidatorIndex(pending.validator_index)] += pending.amount

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

        return InFlightWithdrawals(pwr_amounts=dict(pwr_amounts), fwr_validators=frozenset(fwr_validators))

    def get_requested_but_not_exiting_validators(self, blockstamp: ReferenceBlockStamp) -> list[LidoValidator]:
        """Validators with a full withdrawal queued in EIP-7002 or the TriggerableWithdrawalsBus, not on exit yet."""
        fwr_validators = self.get_in_flight_withdrawals(blockstamp).fwr_validators
        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)
        return [
            validator
            for validators in lido_validators.values()
            for validator in validators
            if validator.index in fwr_validators
            and not is_on_exit(validator)
            # A consolidating source leaves through the consolidation, not through the withdrawal.
            and validator.consolidating_as_source is None
        ]
