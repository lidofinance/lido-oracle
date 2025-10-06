from typing import Sequence

from src.constants import (
    CHURN_LIMIT_QUOTIENT,
    COMPOUNDING_WITHDRAWAL_PREFIX,
    EFFECTIVE_BALANCE_INCREMENT,
    ETH1_ADDRESS_WITHDRAWAL_PREFIX,
    FAR_FUTURE_EPOCH,
    MAX_EFFECTIVE_BALANCE_ELECTRA,
    MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT,
    MAX_SEED_LOOKAHEAD,
    MIN_ACTIVATION_BALANCE,
    MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA,
)
from src.providers.consensus.types import Validator, ValidatorState
from src.types import EpochNumber, Gwei
from src.utils.units import gwei_to_wei


def is_active_validator(validator: Validator, epoch: EpochNumber) -> bool:
    """
    Check if ``validator`` is active.
    https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#is_active_validator
    """
    return validator.validator.activation_epoch <= epoch < validator.validator.exit_epoch


def is_exited_validator(validator: Validator, epoch: EpochNumber) -> bool:
    return validator.validator.exit_epoch <= epoch


def is_on_exit(validator: Validator) -> bool:
    """Validator exited or is going to exit"""
    return validator.validator.exit_epoch != FAR_FUTURE_EPOCH


def is_partially_withdrawable_validator(validator: ValidatorState, balance: Gwei) -> bool:
    """
    Check if ``validator`` is partially withdrawable.
    https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#modified-is_partially_withdrawable_validator
    """
    max_effective_balance = get_max_effective_balance(validator)
    has_max_effective_balance = validator.effective_balance == max_effective_balance
    has_excess_balance = balance > max_effective_balance
    return (
        has_execution_withdrawal_credential(validator)
        and has_max_effective_balance
        and has_excess_balance
    )


def has_far_future_activation_eligibility_epoch(validator: ValidatorState) -> bool:
    """
    Check if ``validator`` has a FAR_FUTURE_EPOCH activation eligibility epoch.
    """
    return validator.activation_eligibility_epoch == FAR_FUTURE_EPOCH


def has_compounding_withdrawal_credential(validator: ValidatorState) -> bool:
    """
    Check if ``validator`` has an 0x02 prefixed "compounding" withdrawal credential.
    https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#new-has_compounding_withdrawal_credential
    """
    return validator.withdrawal_credentials[:4] == COMPOUNDING_WITHDRAWAL_PREFIX


def has_eth1_withdrawal_credential(validator: ValidatorState) -> bool:
    """
    Check if ``validator`` has an 0x01 prefixed "eth1" withdrawal credential.
    https://github.com/ethereum/consensus-specs/blob/dev/specs/capella/beacon-chain.md#has_eth1_withdrawal_credential
    """
    return validator.withdrawal_credentials[:4] == ETH1_ADDRESS_WITHDRAWAL_PREFIX


def has_execution_withdrawal_credential(validator: ValidatorState) -> bool:
    """
    Check if ``validator`` has a 0x01 or 0x02 prefixed withdrawal credential.
    https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#new-has_execution_withdrawal_credential
    """
    return has_compounding_withdrawal_credential(validator) or has_eth1_withdrawal_credential(validator)


def is_fully_withdrawable_validator(validator: ValidatorState, balance: Gwei, epoch: EpochNumber) -> bool:
    """
    Check if `validator` is fully withdrawable
    https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#modified-is_fully_withdrawable_validator
    """
    return (
        has_execution_withdrawal_credential(validator)
        and validator.withdrawable_epoch <= epoch
        and balance > Gwei(0)
    )


def calculate_total_active_effective_balance(all_validators: Sequence[Validator], ref_epoch: EpochNumber) -> Gwei:
    """
    Return the combined effective balance of the active validators.
    Note: returns ``EFFECTIVE_BALANCE_INCREMENT`` Gwei minimum to avoid divisions by zero.
    https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#get_total_active_balance
    """
    total_effective_balance = calculate_active_effective_balance_sum(all_validators, ref_epoch)
    return Gwei(max(EFFECTIVE_BALANCE_INCREMENT, total_effective_balance))


def calculate_active_effective_balance_sum(validators: Sequence[Validator], ref_epoch: EpochNumber) -> Gwei:
    """
    Return the combined effective balance of the active validators from the given list
    """
    effective_balance_sum = 0

    for validator in validators:
        if is_active_validator(validator, ref_epoch):
            effective_balance_sum += validator.validator.effective_balance

    return Gwei(effective_balance_sum)


def compute_activation_exit_epoch(ref_epoch: EpochNumber):
    """
    Return the epoch during which validator activations and exits initiated in ``ref_epoch`` take effect.

    Spec: https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#compute_activation_exit_epoch
    """
    return ref_epoch + 1 + MAX_SEED_LOOKAHEAD


# @see https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#new-get_activation_exit_churn_limit
def get_activation_exit_churn_limit(total_active_balance: Gwei) -> Gwei:
    return min(MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT, get_balance_churn_limit(total_active_balance))


# @see https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#new-get_balance_churn_limit
def get_balance_churn_limit(total_active_balance: Gwei) -> Gwei:
    churn = max(MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA, total_active_balance // CHURN_LIMIT_QUOTIENT)
    return Gwei(churn - churn % EFFECTIVE_BALANCE_INCREMENT)


def get_max_effective_balance(validator: ValidatorState) -> Gwei:
    """
    Get max effective balance for ``validator``.
    https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#new-get_max_effective_balance
    """
    if has_compounding_withdrawal_credential(validator):
        return MAX_EFFECTIVE_BALANCE_ELECTRA
    return MIN_ACTIVATION_BALANCE


def calculate_vault_validators_balances(validators: list[Validator]) -> int:
    return sum(gwei_to_wei(validator.balance) for validator in validators)
