from typing import Sequence

from src.constants import (
    MAX_EFFECTIVE_BALANCE,
    ETH1_ADDRESS_WITHDRAWAL_PREFIX,
    SHARD_COMMITTEE_PERIOD,
    FAR_FUTURE_EPOCH,
)
from src.providers.consensus.typings import Validator
from src.typings import EpochNumber, Gwei


def is_active_validator(validator: Validator, epoch: EpochNumber) -> bool:
    """
    Check if ``validator`` is active.
    https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#is_active_validator
    """
    return int(validator.validator.activation_epoch) <= epoch < int(validator.validator.exit_epoch)


def is_exited_validator(validator: Validator, epoch: EpochNumber) -> bool:
    return int(validator.validator.exit_epoch) <= epoch


def is_on_exit(validator: Validator) -> bool:
    """Validator exited or is going to exit"""
    return int(validator.validator.exit_epoch) != FAR_FUTURE_EPOCH


def is_partially_withdrawable_validator(validator: Validator) -> bool:
    """
    Check if `validator` is partially withdrawable
    https://github.com/ethereum/consensus-specs/blob/dev/specs/capella/beacon-chain.md#is_partially_withdrawable_validator
    """
    has_max_effective_balance = int(validator.validator.effective_balance) == MAX_EFFECTIVE_BALANCE
    has_excess_balance = int(validator.balance) > MAX_EFFECTIVE_BALANCE
    return (
        has_eth1_withdrawal_credential(validator)
        and has_max_effective_balance
        and has_excess_balance
    )


def has_eth1_withdrawal_credential(validator: Validator) -> bool:
    """
    Check if ``validator`` has an 0x01 prefixed "eth1" withdrawal credential.
    https://github.com/ethereum/consensus-specs/blob/dev/specs/capella/beacon-chain.md#has_eth1_withdrawal_credential
    """
    return validator.validator.withdrawal_credentials[:4] == ETH1_ADDRESS_WITHDRAWAL_PREFIX


def is_fully_withdrawable_validator(validator: Validator, epoch: EpochNumber) -> bool:
    """
    Check if `validator` is fully withdrawable
    https://github.com/ethereum/consensus-specs/blob/dev/specs/capella/beacon-chain.md#is_fully_withdrawable_validator
    """
    return (
        has_eth1_withdrawal_credential(validator)
        and EpochNumber(int(validator.validator.withdrawable_epoch)) <= epoch
        and Gwei(int(validator.balance)) > Gwei(0)
    )


def is_validator_eligible_to_exit(validator: Validator, epoch: EpochNumber) -> bool:
    """
    Check if `validator` can exit.
    Verify the validator has been active long enough.
    https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#voluntary-exits
    """
    active_long_enough = int(validator.validator.activation_epoch) + SHARD_COMMITTEE_PERIOD <= epoch
    return active_long_enough and not is_on_exit(validator)


def calculate_active_effective_balance_sum(validators: Sequence[Validator], ref_epoch: EpochNumber) -> Gwei:
    """
    Return the combined effective balance of the active validators.
    https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#get_total_active_balance
    """
    total_effective_balance = 0

    for v in validators:
        if is_active_validator(v, ref_epoch):
            total_effective_balance += int(v.validator.effective_balance)

    return Gwei(total_effective_balance)
