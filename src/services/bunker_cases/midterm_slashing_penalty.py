import logging
from collections import defaultdict
from typing import Mapping

from src.constants import (
    EPOCHS_PER_SLASHINGS_VECTOR,
    MIN_VALIDATOR_WITHDRAWABILITY_DELAY,
    PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX,
    EFFECTIVE_BALANCE_INCREMENT
)
from src.modules.submodules.typings import FrameConfig
from src.providers.consensus.typings import Validator
from src.typings import EpochNumber, Gwei, ReferenceBlockStamp
from src.utils.validator_state import calculate_total_active_effective_balance
from src.web3py.extensions.lido_validators import LidoValidator
from src.web3py.typings import Web3


logger = logging.getLogger(__name__)


class MidtermSlashingPenalty:

    f_conf: FrameConfig
    all_validators: dict[str, Validator]
    lido_validators: dict[str, LidoValidator]

    def __init__(self, w3: Web3):
        self.w3 = w3

    def is_high_midterm_slashing_penalty(self, blockstamp: ReferenceBlockStamp, cl_rebase: Gwei) -> bool:
        logger.info({"msg": "Detecting high midterm slashing penalty"})
        all_slashed_validators = MidtermSlashingPenalty.not_withdrawn_slashed_validators(
            self.all_validators, blockstamp.ref_epoch
        )
        lido_slashed_validators = MidtermSlashingPenalty.not_withdrawn_slashed_validators(
            self.lido_validators, blockstamp.ref_epoch
        )
        logger.info({"msg": f"Slashed: All={len(all_slashed_validators)} | Lido={len(lido_slashed_validators)}"})

        future_midterm_penalty_lido_slashed_validators = {
            k: v for k, v in lido_slashed_validators.items()
            if MidtermSlashingPenalty.get_midterm_slashing_epoch(v) > blockstamp.ref_epoch
        }
        # If no one Lido in current not withdrawn slashed validators
        # and no one midterm slashing epoch in the future - no need to bunker
        if not future_midterm_penalty_lido_slashed_validators:
            return False

        # We should calculate total_balance for each bucket, but we do it once for all per_epoch_buckets
        total_balance = calculate_total_active_effective_balance(self.all_validators, blockstamp.ref_epoch)
        # Calculate lido midterm penalties in each epoch where lido slashed
        per_epoch_buckets = MidtermSlashingPenalty.get_per_epoch_buckets(
            future_midterm_penalty_lido_slashed_validators, blockstamp.ref_epoch
        )
        per_epoch_lido_midterm_penalties = MidtermSlashingPenalty.get_per_epoch_lido_midterm_penalties(
            per_epoch_buckets, future_midterm_penalty_lido_slashed_validators, total_balance
        )
        # Calculate lido midterm penalties impact in each frame
        per_frame_buckets = MidtermSlashingPenalty.get_per_frame_lido_midterm_penalties(
            per_epoch_lido_midterm_penalties, self.f_conf
        )

        # If any midterm penalty sum of lido validators in frame bucket greater than rebase we should trigger bunker
        max_lido_midterm_penalty = max(per_frame_buckets)
        logger.info({"msg": f"Max lido midterm penalty: {max_lido_midterm_penalty}"})
        # Compare with current CL rebase, because we can't predict how much CL rebase will be in the next frames
        # and whether they will cover future midterm penalties, so that the bunker is better to be turned on than not
        if max_lido_midterm_penalty > cl_rebase:
            return True

        return False

    @staticmethod
    def get_per_epoch_buckets(
        all_slashed_validators: dict[str, Validator], ref_epoch: EpochNumber
    ) -> dict[EpochNumber, dict[str, Validator]]:
        """
        Fill per_epoch_buckets by possible slashed epochs
        It detects slashing epoch range for validator
        If difference between validator's withdrawable epoch and exit epoch is greater enough,
        then we can be sure that validator was slashed in particular epoch
        Otherwise, we can only assume that validator was slashed in epochs range
        due because its exit epoch shifted because of huge exit queue

        Read more here:
        https://github.com/ethereum/consensus-specs/blob/dev/specs/altair/beacon-chain.md#modified-slash_validator
        https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#initiate_validator_exit
        """
        per_epoch_buckets: dict[EpochNumber, dict[str, Validator]] = defaultdict(dict[str, Validator])
        for key, validator in all_slashed_validators.items():
            v = validator.validator
            if not v.slashed:
                raise ValueError("Validator should be slashed to detect slashing epoch range")
            if int(v.withdrawable_epoch) - int(v.exit_epoch) > MIN_VALIDATOR_WITHDRAWABILITY_DELAY:
                determined_slashed_epoch = EpochNumber(int(v.withdrawable_epoch) - EPOCHS_PER_SLASHINGS_VECTOR)
                per_epoch_buckets[determined_slashed_epoch][key] = validator
                continue

            possible_slashed_epoch = int(v.withdrawable_epoch) - EPOCHS_PER_SLASHINGS_VECTOR
            for epoch in range(max(0, ref_epoch - EPOCHS_PER_SLASHINGS_VECTOR), possible_slashed_epoch + 1):
                per_epoch_buckets[EpochNumber(epoch)][key] = validator

        return per_epoch_buckets

    @staticmethod
    def not_withdrawn_slashed_validators(
        all_validators: Mapping[str, Validator], ref_epoch: EpochNumber
    ) -> dict[str, Validator]:
        """
        Get all slashed validators, who are not withdrawn yet
        """
        slashed_validators: dict[str, Validator] = {}

        for key, v in all_validators.items():
            if v.validator.slashed and int(v.validator.withdrawable_epoch) > ref_epoch:
                slashed_validators[key] = v

        return slashed_validators

    @staticmethod
    def get_per_epoch_lido_midterm_penalties(
        per_epoch_buckets: dict[EpochNumber, dict[str, Validator]],
        lido_slashed_validators: dict[str, Validator],
        total_balance: Gwei,
    ) -> dict[EpochNumber, dict[str, Gwei]]:
        """
        Iterate through per_epoch_buckets and calculate lido midterm penalties for each bucket
        """
        per_epoch_lido_midterm_penalties: dict[EpochNumber, dict[str, Gwei]] = defaultdict(dict)
        for key, v in lido_slashed_validators.items():
            midterm_penalty_epoch = MidtermSlashingPenalty.get_midterm_slashing_epoch(v)
            # We should calculate midterm penalties by sum of slashings which bound with midterm penalty epoch
            bound_slashed_validators = MidtermSlashingPenalty.get_bound_slashed_validators(
                per_epoch_buckets, midterm_penalty_epoch
            )
            slashings = sum(int(v.validator.effective_balance) for v in bound_slashed_validators.values())
            adjusted_total_slashing_balance = min(
                slashings * PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX,
                total_balance
            )
            effective_balance = int(v.validator.effective_balance)
            penalty_numerator = effective_balance // EFFECTIVE_BALANCE_INCREMENT * adjusted_total_slashing_balance
            penalty = penalty_numerator // total_balance * EFFECTIVE_BALANCE_INCREMENT
            per_epoch_lido_midterm_penalties[midterm_penalty_epoch][key] = Gwei(penalty)
        return per_epoch_lido_midterm_penalties

    @staticmethod
    def get_per_frame_lido_midterm_penalties(
        per_epoch_lido_midterm_penalties: dict[EpochNumber, dict[str, Gwei]],
        frame_config: FrameConfig,
    ) -> list[Gwei]:
        """
        Put per epoch buckets into per frame buckets to calculate lido midterm penalties impact in each frame
        """
        per_frame_buckets: dict[int, dict[str, Gwei]] = defaultdict(dict)
        for epoch, validator_penalty in per_epoch_lido_midterm_penalties.items():
            frame_index = MidtermSlashingPenalty.get_frame_by_epoch(epoch, frame_config)
            for val_key, penalty in validator_penalty.items():
                per_frame_buckets[frame_index][val_key] = (
                    max(penalty, per_frame_buckets[frame_index].get(val_key, Gwei(0)))
                )
        return [Gwei(sum(penalties.values())) for penalties in per_frame_buckets.values()]

    @staticmethod
    def get_bound_slashed_validators(
        per_epoch_buckets: dict[EpochNumber, dict[str, Validator]],
        bound_with_epoch: EpochNumber
    ) -> dict[str, Validator]:
        """
        Get bounded slashed validators for particular epoch
        All slashings that happened in the nearest EPOCHS_PER_SLASHINGS_VECTOR ago considered as bounded
        """
        min_bucket_epoch = min(per_epoch_buckets.keys())
        min_bounded_epoch = max(min_bucket_epoch, EpochNumber(bound_with_epoch - EPOCHS_PER_SLASHINGS_VECTOR))
        bounded_slashed_validators: dict[str, Validator] = {}
        for epoch, slashed_validators in per_epoch_buckets.items():
            if min_bounded_epoch <= epoch <= bound_with_epoch:
                for key, validator in slashed_validators.items():
                    if key not in bounded_slashed_validators:
                        bounded_slashed_validators[key] = validator
        return bounded_slashed_validators

    @staticmethod
    def get_frame_by_epoch(epoch: EpochNumber, frame_config: FrameConfig) -> int:
        return abs(epoch - frame_config.initial_epoch) // frame_config.epochs_per_frame

    @staticmethod
    def get_midterm_slashing_epoch(validator: Validator) -> EpochNumber:
        return EpochNumber(int(validator.validator.withdrawable_epoch) - EPOCHS_PER_SLASHINGS_VECTOR // 2)
