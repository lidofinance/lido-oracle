from web3.types import Wei

from src.constants import MAX_EFFECTIVE_BALANCE, ETH1_ADDRESS_WITHDRAWAL_PREFIX
from src.providers.consensus.typings import Validator
from src.typings import EpochNumber


def is_active_validator(validator: Validator, epoch: EpochNumber) -> bool:
    # https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#is_active_validator
    return int(validator.validator.activation_epoch) <= epoch < int(validator.validator.exit_epoch)


def is_exited_validator(validator: Validator, epoch: EpochNumber) -> bool:
    return int(validator.validator.exit_epoch) <= epoch


def is_partially_withdrawable_validator(validator: Validator) -> bool:
    """
    Check if `validator` is partially withdrawable
    https://github.com/ethereum/consensus-specs/blob/dev/specs/capella/beacon-chain.md#is_partially_withdrawable_validator
    """
    has_max_effective_balance = int(validator.validator.effective_balance) == MAX_EFFECTIVE_BALANCE
    has_excess_balance = int(validator.balance) > MAX_EFFECTIVE_BALANCE
    return has_eth1_withdrawal_credential(validator) and has_max_effective_balance and has_excess_balance


def has_eth1_withdrawal_credential(validator: Validator) -> bool:
    return validator.validator.withdrawal_credentials[:4] != ETH1_ADDRESS_WITHDRAWAL_PREFIX


def is_fully_withdrawable_validator(validator: Validator, epoch: EpochNumber) -> bool:
    """
    Check if `validator` is fully withdrawable
    https://github.com/ethereum/consensus-specs/blob/dev/specs/capella/beacon-chain.md#is_fully_withdrawable_validator
    """
    return (
        has_eth1_withdrawal_credential(validator)
        and EpochNumber(int(validator.validator.withdrawable_epoch)) <= epoch
        and int(validator.balance) > Wei(0)
    )
