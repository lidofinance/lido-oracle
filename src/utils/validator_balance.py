from src.types import Gwei
from src.utils.validator_state import get_max_effective_balance
from src.web3py.extensions.lido_validators import LidoValidator


def get_predictable_full_balance(validator: LidoValidator) -> Gwei:
    """
    Calculates the total balance of a validator including pending deposits and consolidations.
    """
    total_balance = validator.balance

    for pending_deposit in validator.pending_topups:
        total_balance += pending_deposit.amount

    for consolidation in validator.consolidating_as_target:
        total_balance += consolidation.amount

    return total_balance


def get_predictable_balance(validator: LidoValidator) -> Gwei:
    """
    Computes the effective validator balance, accounting for pending sweeps of any excess balance above the effective
    balance.
    """
    max_effective_balance = get_max_effective_balance(validator.validator)
    predictable_full_balance = get_predictable_full_balance(validator)
    return min(predictable_full_balance, max_effective_balance)


def get_predictable_sweep(validator: LidoValidator) -> Gwei:
    """
    Computes the expected sweep payout for a validator, based on the excess balance above the effective balance.
    """
    predictable_full_balance = get_predictable_full_balance(validator)
    max_effective_balance = get_max_effective_balance(validator.validator)

    effective_balance = min(predictable_full_balance, max_effective_balance)

    return Gwei(predictable_full_balance - effective_balance)
