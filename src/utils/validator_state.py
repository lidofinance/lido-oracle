from src.providers.consensus.typings import Validator
from src.typings import EpochNumber


def is_validator_active(validator: Validator, ref_epoch: EpochNumber) -> bool:
    return int(validator.validator.activation_epoch) <= ref_epoch < int(validator.validator.exit_epoch)
