import math
from collections import defaultdict
from dataclasses import dataclass
from typing import List

from src.constants import (
    FAR_FUTURE_EPOCH,
    MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP,
    MAX_WITHDRAWALS_PER_PAYLOAD,
    MIN_ACTIVATION_BALANCE,
)
from src.modules.submodules.types import ChainConfig
from src.providers.consensus.types import BeaconStateView
from src.types import Gwei
from src.utils.validator_state import (
    get_max_effective_balance,
    is_fully_withdrawable_validator,
    is_partially_withdrawable_validator,
)
from src.utils.web3converter import epoch_from_slot


@dataclass
class Withdrawal:
    validator_index: int
    amount: int


def get_sweep_delay_in_epochs(state: BeaconStateView, spec: ChainConfig) -> int:
    """
    This method predicts the average withdrawal delay in epochs.
    It is assumed that on average, a validator sweep is achieved in half the time of a full sweep cycle.
    """

    withdrawals_number_in_sweep_cycle = predict_withdrawals_number_in_sweep_cycle(state, spec.slots_per_epoch)
    full_sweep_cycle_in_epochs = math.ceil(
        withdrawals_number_in_sweep_cycle / MAX_WITHDRAWALS_PER_PAYLOAD / spec.slots_per_epoch
    )

    return full_sweep_cycle_in_epochs // 2


def predict_withdrawals_number_in_sweep_cycle(state: BeaconStateView, slots_per_epoch: int) -> int:
    """
    This method predicts the number of withdrawals that can be performed in a single sweep cycle.
    https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#modified-get_expected_withdrawals

    The prediction is based on the following assumptions:
    - All pending_partial_withdrawals have reached withdrawable_epoch and do not have any processing delays;
    - All pending_partial_withdrawals are executed before full and partial withdrawals, and the result
        is immediately reflected in the validators' balances;
    - The limit MAX_VALIDATORS_PER_WITHDRAWALS_SWEEP is never reached.

    It is assumed that MAX_VALIDATORS_PER_WITHDRAWALS_SWEEP is never reached.
    Even with an extremely low rate of active validators (~0.17% or about 3,500 out of 2,000,000),
    the probability of encountering fewer than 16 MAX_WITHDRAWALS_PER_PAYLOAD active validators
    in any group of 16,384 MAX_VALIDATORS_PER_WITHDRAWALS_SWEEP consecutive validators is less than 1%.
    This makes such an event extremely unlikely. More details can be found in the research: https://hackmd.io/@lido/HyrhJeLOJe.
    """
    pending_partial_withdrawals = get_pending_partial_withdrawals(state)
    validators_withdrawals = get_validators_withdrawals(state, pending_partial_withdrawals, slots_per_epoch)

    pending_partial_withdrawals_number = len(pending_partial_withdrawals)
    validators_withdrawals_number = len(validators_withdrawals)

    # Each payload can have no more than MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP
    # pending partials out of MAX_WITHDRAWALS_PER_PAYLOAD
    # https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#modified-get_expected_withdrawals
    #
    #
    # No partials:   [0 1 2 3], [4 5 6 7], [8 9 0 1], ...
    #                 ^                         ^ cycle
    # With partials: [p p 0 1], [p p 2 3], [p p 4 5], [p p 6 7], [p p 8 9], [p p 0 1], ...
    #                     ^                                                      ^ cycle
    # [ ] - payload
    # 0-9 - index of validator being withdrawn
    #   p - pending partial withdrawal
    #
    # Thus, the ratio of the maximum number of `pending_partial_withdrawals` to the remaining number
    # of `validators_withdrawals` in a single payload is calculated as:
    #
    # pending_partial_withdrawals                  MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP
    # ---------------------------- = ------------------------------------------------------------------------
    #    validators_withdrawals      MAX_WITHDRAWALS_PER_PAYLOAD - MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP

    partial_withdrawals_max_ratio = MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP / (
        MAX_WITHDRAWALS_PER_PAYLOAD - MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP
    )

    pending_partial_withdrawals_max_number_in_cycle = math.ceil(
        validators_withdrawals_number * partial_withdrawals_max_ratio
    )

    pending_partial_withdrawals_number_in_cycle = min(
        pending_partial_withdrawals_number, pending_partial_withdrawals_max_number_in_cycle
    )

    withdrawals_number = validators_withdrawals_number + pending_partial_withdrawals_number_in_cycle

    return withdrawals_number


def get_pending_partial_withdrawals(state: BeaconStateView) -> List[Withdrawal]:
    """
    This method returns withdrawals that can be performed from `state.pending_partial_withdrawals`
    https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#modified-get_expected_withdrawals
    """
    withdrawals: List[Withdrawal] = []

    for withdrawal in state.pending_partial_withdrawals:
        # if withdrawal.withdrawable_epoch > epoch or len(withdrawals) == MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP:
        #     break
        #
        # These checks from the original method are omitted. It is assumed that `withdrawable_epoch`
        # has arrived for all `pending_partial_withdrawals`
        index = withdrawal.validator_index
        validator = state.validators[index]
        has_sufficient_effective_balance = validator.effective_balance >= MIN_ACTIVATION_BALANCE
        has_excess_balance = state.balances[index] > MIN_ACTIVATION_BALANCE

        if validator.exit_epoch == FAR_FUTURE_EPOCH and has_sufficient_effective_balance and has_excess_balance:
            withdrawable_balance = min(state.balances[index] - MIN_ACTIVATION_BALANCE, withdrawal.amount)
            withdrawals.append(
                Withdrawal(
                    validator_index=index,
                    amount=withdrawable_balance,
                )
            )

    return withdrawals


def get_validators_withdrawals(state: BeaconStateView, partial_withdrawals: List[Withdrawal], slots_per_epoch: int) -> List[Withdrawal]:
    """
    This method returns fully and partial withdrawals that can be performed for validators
    https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#modified-get_expected_withdrawals
    """
    epoch = epoch_from_slot(state.slot, slots_per_epoch)
    withdrawals = []
    partially_withdrawn_map: dict[int, int] = defaultdict(int)

    for withdrawal in partial_withdrawals:
        partially_withdrawn_map[withdrawal.validator_index] += withdrawal.amount

    for validator_index, validator in enumerate(state.indexed_validators):
        partially_withdrawn_balance = Gwei(partially_withdrawn_map.get(validator_index, 0))
        balance = Gwei(state.balances[validator_index] - partially_withdrawn_balance)

        if is_fully_withdrawable_validator(validator.validator, balance, epoch):
            withdrawals.append(Withdrawal(validator_index=validator_index, amount=balance))
        elif is_partially_withdrawable_validator(validator.validator, balance):
            max_effective_balance = get_max_effective_balance(validator.validator)
            withdrawals.append(
                Withdrawal(
                    validator_index=validator_index,
                    amount=balance - max_effective_balance,
                )
            )

    return withdrawals
