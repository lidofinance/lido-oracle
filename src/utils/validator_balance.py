from src.providers.consensus.types import ExpectedWithdrawal
from src.types import Gwei, ValidatorIndex
from src.utils.validator_state import get_max_effective_balance
from src.web3py.extensions.lido_validators import LidoValidator


def gloas_balance_correction(
    expected_withdrawals: list[ExpectedWithdrawal],
    lido_indices: set[ValidatorIndex],
) -> Gwei:
    """Sum of Glamsterdam (EIP-7732) pending withdrawal amounts for the given Lido validator indices.

    Under Gloas, process_withdrawals deducts CL balances before the EL payload delivers
    the matching credits to the withdrawal vault. Adding this back restores TVL consistency.
    """
    return Gwei(sum(w.amount for w in expected_withdrawals if w.validator_index in lido_indices))


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
