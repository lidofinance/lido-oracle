from typing import Sequence

from src.constants import FAR_FUTURE_EPOCH
from src.providers.consensus.typings import Validator, BeaconSpecResponse
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


def get_validator_age(validator: Validator, ref_epoch: EpochNumber) -> int:
    """Validator age in epochs from activation to ref_epoch"""
    return max(ref_epoch - int(validator.validator.activation_epoch), 0)


def is_partially_withdrawable_validator(spec: BeaconSpecResponse, validator: Validator) -> bool:
    """
    Check if `validator` is partially withdrawable
    https://github.com/ethereum/consensus-specs/blob/dev/specs/capella/beacon-chain.md#is_partially_withdrawable_validator
    """
    has_max_effective_balance = int(validator.validator.effective_balance) == int(spec.MAX_EFFECTIVE_BALANCE)
    has_excess_balance = int(validator.balance) > int(spec.MAX_EFFECTIVE_BALANCE)
    return (
        has_eth1_withdrawal_credential(spec, validator)
        and has_max_effective_balance
        and has_excess_balance
    )


def has_eth1_withdrawal_credential(spec: BeaconSpecResponse, validator: Validator) -> bool:
    """
    Check if ``validator`` has an 0x01 prefixed "eth1" withdrawal credential.
    https://github.com/ethereum/consensus-specs/blob/dev/specs/capella/beacon-chain.md#has_eth1_withdrawal_credential
    """
    return validator.validator.withdrawal_credentials[:4] == spec.ETH1_ADDRESS_WITHDRAWAL_PREFIX


def is_fully_withdrawable_validator(spec: BeaconSpecResponse, validator: Validator, epoch: EpochNumber) -> bool:
    """
    Check if `validator` is fully withdrawable
    https://github.com/ethereum/consensus-specs/blob/dev/specs/capella/beacon-chain.md#is_fully_withdrawable_validator
    """
    return (
        has_eth1_withdrawal_credential(spec, validator)
        and EpochNumber(int(validator.validator.withdrawable_epoch)) <= epoch
        and Gwei(int(validator.balance)) > Gwei(0)
    )


def is_validator_eligible_to_exit(spec: BeaconSpecResponse, validator: Validator, epoch: EpochNumber) -> bool:
    """
    Check if `validator` can exit.
    Verify the validator has been active long enough.
    https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#voluntary-exits
    """
    active_long_enough = int(validator.validator.activation_epoch) + int(spec.SHARD_COMMITTEE_PERIOD) <= epoch
    return active_long_enough and not is_on_exit(validator)


def calculate_total_active_effective_balance(spec: BeaconSpecResponse, all_validators: Sequence[Validator], ref_epoch: EpochNumber) -> Gwei:
    """
    Return the combined effective balance of the active validators.
    Note: returns ``EFFECTIVE_BALANCE_INCREMENT`` Gwei minimum to avoid divisions by zero.
    https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#get_total_active_balance
    """
    total_effective_balance = calculate_active_effective_balance_sum(all_validators, ref_epoch)
    return Gwei(max(int(spec.EFFECTIVE_BALANCE_INCREMENT), total_effective_balance))


def calculate_active_effective_balance_sum(validators: Sequence[Validator], ref_epoch: EpochNumber) -> Gwei:
    """
    Return the combined effective balance of the active validators from the given list
    """
    effective_balance_sum = 0

    for validator in validators:
        if is_active_validator(validator, ref_epoch):
            effective_balance_sum += int(validator.validator.effective_balance)

    return Gwei(effective_balance_sum)
