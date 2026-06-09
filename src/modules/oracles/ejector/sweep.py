import math
from collections import defaultdict
from dataclasses import dataclass

from src.constants import (
    FAR_FUTURE_EPOCH,
    MAX_WITHDRAWALS_PER_PAYLOAD,
    MIN_ACTIVATION_BALANCE,
)
from src.modules.common.types import ChainConfig
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


def get_sweep_delay_in_epochs(
    state: BeaconStateView,
    spec: ChainConfig,
    is_epbs_active: bool = False,
) -> int:
    """
    Predicts the average withdrawal delay in epochs for a validator in the sweep queue.

    Average delay = full_sweep_cycle // 2 (cursor is on average halfway to the target validator).
    """
    withdrawals_number, available_per_payload = predict_withdrawals_number_in_sweep_cycle(
        state, spec.slots_per_epoch, is_epbs_active
    )
    full_sweep_cycle_in_epochs = math.ceil(
        withdrawals_number / available_per_payload / spec.slots_per_epoch
    )
    return full_sweep_cycle_in_epochs // 2


def predict_withdrawals_number_in_sweep_cycle(
    state: BeaconStateView,
    slots_per_epoch: int,
    is_epbs_active: bool = False,
) -> tuple[int, int]:
    """
    Returns (withdrawals_number, available_per_payload) for one validator sweep cycle.

    Pending partials are excluded from both the numerator and denominator:
    - numerator: no pending_partials added to withdrawals_number
    - denominator: no partial cap subtracted from available_per_payload
    This guarantees estimated delay <= real sweep delay: ejector requests at least as
    many exits as a spec-faithful model would.

    Post-ePBS: builder_pending_withdrawals are a real protocol constraint (~1 slot) and
    are subtracted from available_per_payload. They are not externally manipulable via
    EIP-7002, so including them does not open an attack surface.

    Assumption: MAX_VALIDATORS_PER_WITHDRAWALS_SWEEP is never reached.
    """
    validators_withdrawals = get_validators_withdrawals(state, [], slots_per_epoch)

    if is_epbs_active:
        builder_pending_per_block = min(len(state.builder_pending_withdrawals), MAX_WITHDRAWALS_PER_PAYLOAD - 1)
        available_per_payload = MAX_WITHDRAWALS_PER_PAYLOAD - builder_pending_per_block
    else:
        available_per_payload = MAX_WITHDRAWALS_PER_PAYLOAD

    return len(validators_withdrawals), available_per_payload


def get_pending_partial_withdrawals(state: BeaconStateView) -> list[Withdrawal]:
    """
    This method returns withdrawals that can be performed from `state.pending_partial_withdrawals`
    https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#modified-get_expected_withdrawals
    """
    withdrawals: list[Withdrawal] = []

    for withdrawal in state.pending_partial_withdrawals:
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


def get_validators_withdrawals(
    state: BeaconStateView, partial_withdrawals: list[Withdrawal], slots_per_epoch: int
) -> list[Withdrawal]:
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
