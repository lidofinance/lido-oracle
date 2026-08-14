from collections import defaultdict

from src.providers.consensus.types import ExpectedWithdrawal
from src.types import Gwei, ValidatorIndex
from src.utils.validator_state import get_max_effective_balance
from src.web3py.extensions.lido_validators import LidoValidator


def gloas_correction_by_index(expected_withdrawals: list[ExpectedWithdrawal]) -> dict[ValidatorIndex, Gwei]:
    """Per-validator sum of EIP-7732 in-flight withdrawal amounts.

    A single payload can carry more than one withdrawal for the same validator: the pending-partial
    queue may hold several EIP-7002 requests for it, and the validator sweep does not skip a
    validator already served earlier in the same payload — it only recomputes the balance via
    `get_balance_after_withdrawals`. Amounts must therefore be summed per index, never overwritten.
    """
    by_index: defaultdict[ValidatorIndex, Gwei] = defaultdict(lambda: Gwei(0))
    for withdrawal in expected_withdrawals:
        by_index[withdrawal.validator_index] = Gwei(by_index[withdrawal.validator_index] + withdrawal.amount)
    return dict(by_index)


def gloas_balance_correction(
    expected_withdrawals: list[ExpectedWithdrawal],
    lido_indices: set[ValidatorIndex],
) -> Gwei:
    """Sum of EIP-7732 in-flight withdrawal amounts for the given Lido validator indices.

    Under Gloas, process_withdrawals reduces CL balances before the execution payload credits the
    withdrawal vault, so the oracle adds these amounts back to keep the CL-side balance sum
    consistent with the (not-yet-credited) EL side. Pre-fork states carry no such withdrawals and
    the sum is zero.

    Restricting to Lido validator indices also excludes EIP-7732 builder-registry entries
    (index >= 2**40) automatically, since Lido validator indices are far below that.
    """
    return Gwei(sum((w.amount for w in expected_withdrawals if w.validator_index in lido_indices), Gwei(0)))


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


def get_predictable_inbound_sweep(validator: LidoValidator) -> Gwei:
    """
    Computes the expected sweep payout for a validator, based on the excess balance above the effective balance.
    """
    predictable_full_balance = get_predictable_full_inbound_balance(validator)
    max_effective_balance = get_max_effective_balance(validator.validator)

    effective_balance = min(predictable_full_balance, max_effective_balance)

    return Gwei(predictable_full_balance - effective_balance)
