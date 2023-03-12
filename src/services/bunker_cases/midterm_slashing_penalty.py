import logging
from collections import defaultdict
from typing import Sequence, TypeVar

from src.constants import (
    EPOCHS_PER_SLASHINGS_VECTOR,
    MIN_VALIDATOR_WITHDRAWABILITY_DELAY,
    PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX,
    EFFECTIVE_BALANCE_INCREMENT
)
from src.modules.submodules.typings import FrameConfig
from src.providers.consensus.typings import Validator
from src.typings import EpochNumber, Gwei, ReferenceBlockStamp, FrameNumber
from src.utils.validator_state import calculate_total_active_effective_balance
from src.web3py.extensions.lido_validators import LidoValidator


logger = logging.getLogger(__name__)


TValidator = TypeVar('TValidator', bound=Validator)


class MidtermSlashingPenalty:

    @staticmethod
    def is_high_midterm_slashing_penalty(
        blockstamp: ReferenceBlockStamp,
        frame_config: FrameConfig,
        all_validators: list[Validator],
        lido_validators: list[LidoValidator],
        frame_cl_rebase: Gwei
    ) -> bool:
        logger.info({"msg": "Detecting high midterm slashing penalty"})
        all_slashed_validators = MidtermSlashingPenalty.get_not_withdrawn_slashed_validators(
            all_validators, blockstamp.ref_epoch
        )
        lido_slashed_validators = MidtermSlashingPenalty.get_not_withdrawn_slashed_validators(
            lido_validators,
            blockstamp.ref_epoch,
        )
        logger.info({"msg": f"Slashed: All={len(all_slashed_validators)} | Lido={len(lido_slashed_validators)}"})

        # Put all Lido slashed validators to future frames by midterm penalty epoch
        future_frames_lido_validators = MidtermSlashingPenalty.get_per_frame_lido_validators_with_future_midterm_epoch(
            blockstamp.ref_epoch,
            frame_config,
            lido_slashed_validators,
        )

        # If no one Lido in current not withdrawn slashed validators
        # and no one midterm slashing epoch in the future - no need to bunker
        if not future_frames_lido_validators:
            return False

        # We should calculate total balance for each midterm penalty epoch, but we can't do it for the future epochs
        # So we get total balance by current ref epoch
        total_balance = calculate_total_active_effective_balance(all_validators, blockstamp.ref_epoch)

        # Calculate sum of Lido midterm penalties in each future frame
        frames_lido_midterm_penalties = MidtermSlashingPenalty.get_future_midterm_penalty_sum_in_frames(
            blockstamp.ref_epoch, all_slashed_validators,  total_balance, future_frames_lido_validators,
        )
        max_lido_midterm_penalty = max(frames_lido_midterm_penalties.values()) if frames_lido_midterm_penalties else 0
        logger.info({"msg": f"Max lido midterm penalty: {max_lido_midterm_penalty}"})

        # Compare with current CL rebase, because we can't predict how much CL rebase will be in the next frames
        # and whether they will cover future midterm penalties, so that the bunker is better to be turned on than not
        if max_lido_midterm_penalty > frame_cl_rebase:
            return True

        return False

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
        return list(map(lambda x: EpochNumber(x), range(earliest_slashed_epoch, latest_slashed_epoch + 1)))

    @staticmethod
    def get_per_frame_lido_validators_with_future_midterm_epoch(
        ref_epoch: EpochNumber,
        frame_config: FrameConfig,
        midterm_penalty_slashed_validators: list[LidoValidator],
    ) -> dict[FrameNumber, list[LidoValidator]]:
        """
        Put per midterm penalty epoch buckets into per frame buckets to calculate penalties impact in each frame
        """
        buckets: dict[FrameNumber, list[LidoValidator]] = defaultdict(list[LidoValidator])
        for validator in midterm_penalty_slashed_validators:
            midterm_epoch = MidtermSlashingPenalty.get_midterm_slashing_epoch(validator)
            if midterm_epoch <= ref_epoch:
                # We need midterm penalties only from future frames
                continue
            frame_number = MidtermSlashingPenalty.get_frame_by_epoch(midterm_epoch, frame_config)
            buckets[frame_number].append(validator)

        return buckets

    @staticmethod
    def get_future_midterm_penalty_sum_in_frames(
        ref_epoch: EpochNumber,
        all_slashed_validators: list[Validator],
        total_balance: Gwei,
        per_frame_validators: dict[FrameNumber, list[LidoValidator]],
    ) -> dict[FrameNumber, Gwei]:
        """Calculate sum of midterm penalties in each frame"""
        per_frame_midterm_penalty_sum: dict[FrameNumber, Gwei] = {}
        for frame_number, validators_in_future_frame in per_frame_validators.items():
            per_frame_midterm_penalty_sum[frame_number] = MidtermSlashingPenalty.predict_midterm_penalty_in_frame(
                ref_epoch,
                all_slashed_validators,
                total_balance,
                validators_in_future_frame
            )

        return per_frame_midterm_penalty_sum

    @staticmethod
    def predict_midterm_penalty_in_frame(
        ref_epoch: EpochNumber,
        all_slashed_validators: list[Validator],
        total_balance: Gwei,
        validators_in_frame: list[LidoValidator]
    ) -> Gwei:
        """Predict penalty in frame"""
        penalty_in_frame = 0
        for validator in validators_in_frame:
            midterm_penalty_epoch = MidtermSlashingPenalty.get_midterm_slashing_epoch(validator)
            bound_slashed_validators = MidtermSlashingPenalty.get_bound_with_midterm_epoch_slashed_validators(
                ref_epoch, all_slashed_validators, EpochNumber(midterm_penalty_epoch)
            )
            penalty_in_frame += MidtermSlashingPenalty.get_validator_midterm_penalty(
                validator, len(bound_slashed_validators), total_balance
            )
        return Gwei(penalty_in_frame)

    @staticmethod
    def get_validator_midterm_penalty(
        validator: LidoValidator,
        bound_slashed_validators_count: int,
        total_balance: Gwei
    ) -> Gwei:
        """
        Calculate midterm penalty for particular validator
        https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#slashings
        """
        # We don't know which balance was at slashing epoch, so we make an optimistic assumption that it was 32 ETH
        slashings = Gwei(bound_slashed_validators_count * 32 * 10 ** 9)
        adjusted_total_slashing_balance = min(
            slashings * PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX, total_balance
        )
        effective_balance = int(validator.validator.effective_balance)
        penalty_numerator = effective_balance // EFFECTIVE_BALANCE_INCREMENT * adjusted_total_slashing_balance
        penalty = penalty_numerator // total_balance * EFFECTIVE_BALANCE_INCREMENT

        return Gwei(penalty)

    @staticmethod
    def get_bound_with_midterm_epoch_slashed_validators(
        ref_epoch: EpochNumber,
        slashed_validators: list[Validator],
        midterm_penalty_epoch: EpochNumber,
    ) -> list[Validator]:
        """
        Get bounded slashed validators for particular epoch
        All slashings that happened in the nearest EPOCHS_PER_SLASHINGS_VECTOR ago considered as bounded
        """
        min_bound_epoch = max(0, midterm_penalty_epoch - EPOCHS_PER_SLASHINGS_VECTOR)
        bound_slashings = []
        for validator in slashed_validators:
            possible_slashing_epochs = MidtermSlashingPenalty.get_possible_slashed_epochs(validator, ref_epoch)
            is_bound = any(min_bound_epoch <= epoch <= midterm_penalty_epoch for epoch in possible_slashing_epochs)
            if is_bound:
                bound_slashings.append(validator)
        return bound_slashings

    @staticmethod
    def get_not_withdrawn_slashed_validators(
        all_validators: Sequence[TValidator],
        ref_epoch: EpochNumber
    ) -> list[TValidator]:
        """Get all slashed validators, who are not withdrawn yet"""
        slashed_validators = []

        for v in all_validators:
            if v.validator.slashed and int(v.validator.withdrawable_epoch) > ref_epoch:
                slashed_validators.append(v)

        return slashed_validators

    @staticmethod
    def get_future_midterm_penalty_slashed_validators(
        slashed_validators: dict[str, Validator],
        ref_epoch: EpochNumber,
    ) -> dict[str, Validator]:
        """Get validators, who will get midterm penalty in the future"""
        future_midterm_penalty_lido_slashed_validators: dict[str, Validator] = {}

        for key, v in slashed_validators.items():
            if MidtermSlashingPenalty.get_midterm_slashing_epoch(v) > ref_epoch:
                future_midterm_penalty_lido_slashed_validators[key] = v

        return future_midterm_penalty_lido_slashed_validators

    @staticmethod
    def get_frame_by_epoch(epoch: EpochNumber, frame_config: FrameConfig) -> FrameNumber:
        """Get oracle report frame index by epoch"""
        return FrameNumber((epoch - frame_config.initial_epoch) // frame_config.epochs_per_frame)

    @staticmethod
    def get_midterm_slashing_epoch(validator: Validator) -> EpochNumber:
        """https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#slashings"""
        return EpochNumber(int(validator.validator.withdrawable_epoch) - EPOCHS_PER_SLASHINGS_VECTOR // 2)
