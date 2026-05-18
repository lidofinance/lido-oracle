from src.types import Gwei
from src.utils.validator_state import get_max_effective_balance
from src.web3py.extensions.lido_validators import LidoValidator


def get_predictable_full_inbound_balance(validator: LidoValidator) -> Gwei:
    """
    Returns the predicted balance using only incoming flows: current balance,
    pending top-ups, and consolidations where the validator is the target.

    Outgoing consolidations (`consolidating_as_source`) are NOT subtracted.
    For a validator that is a consolidation source, the result is higher than
    the balance that will actually remain. Callers must skip such validators
    or handle them on their own.
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

    Same caller rules as `get_predictable_full_inbound_balance`: do not pass
    validators with `consolidating_as_source` set.
    """
    max_effective_balance = get_max_effective_balance(validator.validator)
    predictable_full_balance = get_predictable_full_inbound_balance(validator)
    return min(predictable_full_balance, max_effective_balance)


def get_predictable_inbound_sweep(validator: LidoValidator) -> Gwei:
    """
    Returns the amount expected to be swept out: the part of the inbound
    balance that is above the max effective balance.

    Same caller rules as `get_predictable_full_inbound_balance`: do not pass
    validators with `consolidating_as_source` set.
    """
    predictable_full_balance = get_predictable_full_inbound_balance(validator)
    max_effective_balance = get_max_effective_balance(validator.validator)

    effective_balance = min(predictable_full_balance, max_effective_balance)

    return Gwei(predictable_full_balance - effective_balance)
