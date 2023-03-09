import logging
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


logger = logging.getLogger(__name__)


class MidtermSlashingPenalty:

    @staticmethod
    def is_high_midterm_slashing_penalty(
        blockstamp: ReferenceBlockStamp,
        frame_config: FrameConfig,
        all_validators: dict[str, Validator],
        lido_validators: dict[str, LidoValidator],
        frame_cl_rebase: Gwei
    ) -> bool:
        logger.info({"msg": "Detecting high midterm slashing penalty"})
        all_slashed_validators = MidtermSlashingPenalty.get_not_withdrawn_slashed_validators(
            all_validators, blockstamp.ref_epoch
        )
        lido_slashed_validators = MidtermSlashingPenalty.get_not_withdrawn_slashed_validators(
            lido_validators, blockstamp.ref_epoch
        )
        logger.info({"msg": f"Slashed: All={len(all_slashed_validators)} | Lido={len(lido_slashed_validators)}"})

        # We should consider only slashed validators that will get their midterm penalty in the future
        future_penalized_lido_slashed_validators = MidtermSlashingPenalty.get_future_midterm_penalty_slashed_validators(
            lido_slashed_validators, blockstamp.ref_epoch
        )
        # If no one Lido in current not withdrawn slashed validators
        # and no one midterm slashing epoch in the future - no need to bunker
        if not future_penalized_lido_slashed_validators:
            return False

        # We should calculate total balance for each midterm penalty epoch, but we can't do it for the future epochs
        # So we get total balance by current ref epoch
        total_balance = calculate_total_active_effective_balance(list(all_validators.values()), blockstamp.ref_epoch)

        # Put all slashed validators to buckets by possible slashed epoch
        possible_slashed_epoch_buckets = MidtermSlashingPenalty.get_per_possible_slashed_epoch_buckets(
            all_slashed_validators, blockstamp.ref_epoch
        )

        # Put all Lido slashed validators to frames by midterm penalty epoch
        frames_lido_validators = MidtermSlashingPenalty.get_per_frame_lido_validators_with_future_midterm_epoch(
            future_penalized_lido_slashed_validators, frame_config
        )

        # Calculate sum of Lido midterm penalties in each future frame
        frames_lido_midterm_penalties = MidtermSlashingPenalty.get_future_midterm_penalty_sum_in_frames(
            frames_lido_validators, possible_slashed_epoch_buckets, total_balance
        )
        max_lido_midterm_penalty = max(frames_lido_midterm_penalties.values()) if frames_lido_midterm_penalties else 0
        logger.info({"msg": f"Max lido midterm penalty: {max_lido_midterm_penalty}"})

        # Compare with current CL rebase, because we can't predict how much CL rebase will be in the next frames
        # and whether they will cover future midterm penalties, so that the bunker is better to be turned on than not
        if max_lido_midterm_penalty > frame_cl_rebase:
            return True

        return False

    @staticmethod
    def get_per_possible_slashed_epoch_buckets(
        all_slashed_validators: dict[str, Validator],
        ref_epoch: EpochNumber
    ) -> dict[EpochNumber, dict[str, Validator]]:
        """
        Fill epoch number buckets by possible slashed epochs
        """
        buckets: dict[EpochNumber, dict[str, Validator]] = {}
        for key, validator in all_slashed_validators.items():
            possible_slashed_epochs = MidtermSlashingPenalty.get_possible_slashed_epochs(validator, ref_epoch)
            for epoch in possible_slashed_epochs:
                buckets.setdefault(epoch, {})
                buckets[epoch][key] = validator
        return buckets

    @staticmethod
    def get_possible_slashed_epochs(validator: Validator, ref_epoch: EpochNumber) -> list[EpochNumber]:
        """
        It detects slashing epoch range for validator
        If difference between validator's withdrawable epoch and exit epoch is greater enough,
        then we can be sure that validator was slashed in particular epoch
        Otherwise, we can only assume that validator was slashed in epochs range
        due because its exit epoch shifted because of huge exit queue

        Read more here:
        https://github.com/ethereum/consensus-specs/blob/dev/specs/altair/beacon-chain.md#modified-slash_validator
        https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#initiate_validator_exit
        """
        v = validator.validator

        if int(v.withdrawable_epoch) - int(v.exit_epoch) > MIN_VALIDATOR_WITHDRAWABILITY_DELAY:
            determined_slashed_epoch = EpochNumber(int(v.withdrawable_epoch) - EPOCHS_PER_SLASHINGS_VECTOR)
            return [determined_slashed_epoch]

        earliest_slashed_epoch = max(0, ref_epoch - EPOCHS_PER_SLASHINGS_VECTOR)
        latest_slashed_epoch = int(v.withdrawable_epoch) - EPOCHS_PER_SLASHINGS_VECTOR
        return list(range(earliest_slashed_epoch, latest_slashed_epoch + 1))

    @staticmethod
    def get_per_frame_lido_validators_with_future_midterm_epoch(
        future_midterm_penalty_lido_slashed_validators: dict[str, Validator],
        frame_config: FrameConfig,
    ) -> dict[int, dict[int, list[Validator]]]:
        """
        Put per epoch buckets into per frame buckets to calculate lido midterm penalties impact in each frame
        """
        buckets: dict[int, dict[int, list[Validator]]] = {}
        for validator in future_midterm_penalty_lido_slashed_validators.values():
            midterm_epoch = MidtermSlashingPenalty.get_midterm_slashing_epoch(validator)
            frame_index = MidtermSlashingPenalty.get_frame_by_epoch(midterm_epoch, frame_config)
            buckets.setdefault(frame_index, {})
            buckets[frame_index][midterm_epoch] = buckets[frame_index].get(midterm_epoch, []) + [validator]
        return buckets

    @staticmethod
    def get_future_midterm_penalty_sum_in_frames(
        per_frame_validators: dict[int, dict[int, list[Validator]]],
        per_slashing_epoch_buckets: dict[EpochNumber, dict[str, Validator]],
        total_balance: Gwei,
    ) -> dict[int, Gwei]:
        """
        Calculate sum of midterm penalties in each frame
        """
        per_frame_midterm_penalty_sum: dict[int, Gwei] = {}
        for frame_index, validators_in_future_frame in per_frame_validators.items():
            penalty_sum_in_frame = 0
            for midterm_penalty_epoch, midterm_penalty_validators in validators_in_future_frame.items():
                bound_slashed_validators = MidtermSlashingPenalty.get_bound_with_midterm_epoch_slashed_validators(
                    per_slashing_epoch_buckets, EpochNumber(midterm_penalty_epoch)
                )
                adjusted_total_slashing_balance = MidtermSlashingPenalty.get_adjusted_total_slashing_balance(
                    len(bound_slashed_validators), total_balance
                )
                for validator in midterm_penalty_validators:
                    effective_balance = Gwei(int(validator.validator.effective_balance))
                    penalty_sum_in_frame += MidtermSlashingPenalty.get_midterm_penalty(
                        effective_balance, adjusted_total_slashing_balance, total_balance
                    )
            per_frame_midterm_penalty_sum[frame_index] = Gwei(penalty_sum_in_frame)

        return per_frame_midterm_penalty_sum

    @staticmethod
    def get_adjusted_total_slashing_balance(
        bound_slashed_validators_count: int,
        total_balance: Gwei,
    ) -> Gwei:
        """
        Calculate adjusted total slashing balance for particular midterm penalty epoch
        """
        # We don't know which balance was at slashing epoch, so we make an assumption that it was 32 ETH
        slashings = Gwei(bound_slashed_validators_count * 32 * 10 ** 9)
        return min(
            slashings * PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX, total_balance
        )

    @staticmethod
    def get_midterm_penalty(
        effective_balance: Gwei,
        adjusted_total_slashing_balance: Gwei,
        total_balance: Gwei
    ) -> Gwei:
        """
        Calculate midterm penalty for particular validator
        https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#slashings
        """

        penalty_numerator = effective_balance // EFFECTIVE_BALANCE_INCREMENT * adjusted_total_slashing_balance
        penalty = penalty_numerator // total_balance * EFFECTIVE_BALANCE_INCREMENT

        return Gwei(penalty)

    @staticmethod
    def get_bound_with_midterm_epoch_slashed_validators(
        per_slashing_epoch_buckets: dict[EpochNumber, dict[str, Validator]],
        midterm_penalty_epoch: EpochNumber,
    ) -> dict[str, Validator]:
        """
        Get bounded slashed validators for particular epoch
        All slashings that happened in the nearest EPOCHS_PER_SLASHINGS_VECTOR ago considered as bounded
        """
        min_bound_epoch = max(0, midterm_penalty_epoch - EPOCHS_PER_SLASHINGS_VECTOR)
        bounded_slashings: dict[str, Validator] = {}
        for slashing_epoch, slashed_validators in per_slashing_epoch_buckets.items():
            if min_bound_epoch <= slashing_epoch <= midterm_penalty_epoch:
                for pubkey, validator in slashed_validators.items():
                    bounded_slashings[pubkey] = validator
        return bounded_slashings

    @staticmethod
    def get_not_withdrawn_slashed_validators(
        all_validators: Mapping[str, Validator],
        ref_epoch: EpochNumber
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
    def get_future_midterm_penalty_slashed_validators(
        slashed_validators: dict[str, Validator],
        ref_epoch: EpochNumber,
    ) -> dict[str, Validator]:
        """
        Get validators, who will get midterm penalty in the future
        """
        future_midterm_penalty_lido_slashed_validators: dict[str, Validator] = {}

        for key, v in slashed_validators.items():
            if MidtermSlashingPenalty.get_midterm_slashing_epoch(v) > ref_epoch:
                future_midterm_penalty_lido_slashed_validators[key] = v

        return future_midterm_penalty_lido_slashed_validators

    @staticmethod
    def get_frame_by_epoch(epoch: EpochNumber, frame_config: FrameConfig) -> int:
        """
        Get oracle report frame index by epoch
        """
        return (epoch - frame_config.initial_epoch) // frame_config.epochs_per_frame

    @staticmethod
    def get_midterm_slashing_epoch(validator: Validator) -> EpochNumber:
        """
        https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#slashings
        """
        return EpochNumber(int(validator.validator.withdrawable_epoch) - EPOCHS_PER_SLASHINGS_VECTOR // 2)
