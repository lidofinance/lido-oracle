from src.providers.consensus.typings import Validator
from src.typings import EpochNumber


def is_active_validator(validator: Validator, epoch: EpochNumber) -> bool:
    # https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#is_active_validator
    return int(validator.validator.activation_epoch) <= epoch < int(validator.validator.exit_epoch)


def is_exited_validator(validator: Validator, epoch: EpochNumber) -> bool:
    return int(validator.validator.exit_epoch) <= epoch
