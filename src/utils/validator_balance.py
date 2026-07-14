from src.constants import EFFECTIVE_BALANCE_INCREMENT
from src.types import Gwei
from src.utils.validator_state import get_max_effective_balance
from src.web3py.extensions.lido_validators import LidoValidator


def get_predictable_full_inbound_balance(validator: LidoValidator) -> Gwei:
    """
    Returns the predicted balance using only incoming flows: current balance,
    pending top-ups, and consolidations where the validator is the target.

    Outgoing consolidations and withdrawals are NOT subtracted.
    """
    total_balance = validator.balance

    for pending_deposit in validator.pending_topups:
        total_balance += pending_deposit.amount

    for consolidation in validator.consolidating_as_target:
        total_balance += consolidation.amount

    return total_balance


def get_predictable_inbound_balance(validator: LidoValidator) -> Gwei:
    """
    Same as `get_predictable_full_inbound_balance`, but capped at the
    validator's max effective balance. Any amount above the cap is treated
    as sweepable and not included here.
    """
    max_effective_balance = get_max_effective_balance(validator.validator)
    predictable_full_balance = get_predictable_full_inbound_balance(validator)
    return min(predictable_full_balance, max_effective_balance)


def get_predictable_effective_balance(validator: LidoValidator) -> Gwei:
    """
    Same as `get_predictable_inbound_balance`, but the pre-cap balance is floored to the
    nearest `EFFECTIVE_BALANCE_INCREMENT` first, matching the quantization the real chain
    applies to `effective_balance` during epoch processing.

    Intended for churn/exit-epoch prediction, where the chain compares against a
    quantized effective balance.

    Note this is still an approximation of a future value: `balance` keeps growing between
    now and whenever the validator's exit actually gets processed on-chain, and the real
    `effective_balance` only updates once that growth crosses a hysteresis threshold
    (`process_effective_balance_updates`) — so it won't always match exactly either way.
    """
    max_effective_balance = get_max_effective_balance(validator.validator)
    predictable_full_balance = get_predictable_full_inbound_balance(validator)
    floored_balance = Gwei(predictable_full_balance - predictable_full_balance % EFFECTIVE_BALANCE_INCREMENT)
    return min(floored_balance, max_effective_balance)


def get_predictable_inbound_sweep(validator: LidoValidator) -> Gwei:
    """
    Computes the expected sweep payout for a validator, based on the excess balance above the effective balance.
    """
    predictable_full_balance = get_predictable_full_inbound_balance(validator)
    max_effective_balance = get_max_effective_balance(validator.validator)

    effective_balance = min(predictable_full_balance, max_effective_balance)

    return Gwei(predictable_full_balance - effective_balance)
