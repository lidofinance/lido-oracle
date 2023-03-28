import logging
from collections import defaultdict

from src.constants import (
    EPOCHS_PER_SLASHINGS_VECTOR,
    MIN_VALIDATOR_WITHDRAWABILITY_DELAY,
    PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX,
    EFFECTIVE_BALANCE_INCREMENT, MAX_EFFECTIVE_BALANCE
)
from src.modules.submodules.typings import FrameConfig, ChainConfig
from src.providers.consensus.typings import Validator
from src.typings import EpochNumber, Gwei, ReferenceBlockStamp, FrameNumber, SlotNumber
from src.utils.validator_state import calculate_total_active_effective_balance
from src.web3py.extensions.lido_validators import LidoValidator


logger = logging.getLogger(__name__)


class MidtermSlashingPenalty:

    @staticmethod
    def is_high_midterm_slashing_penalty(
        blockstamp: ReferenceBlockStamp,
        frame_config: FrameConfig,
        chain_config: ChainConfig,
        all_validators: list[Validator],
        lido_validators: list[LidoValidator],
        current_report_cl_rebase: Gwei,
        last_report_ref_slot: SlotNumber
    ) -> bool:
        """
        Check if there is a high midterm slashing penalty in the future frames.

        If current report CL rebase contains more than one frame, we should calculate the CL rebase for only one frame
        and compare max midterm penalty with calculated for onel frame CL rebase
        because we assume that reports in the future can be "per-frame" as normal reports.
        So we need to understand can we avoid negative CL rebase because of slashings in the future or not
        """
        logger.info({"msg": "Detecting high midterm slashing penalty"})
        all_slashed_validators = MidtermSlashingPenalty.get_slashed_validators_with_impact_on_midterm_penalties(
            all_validators, blockstamp.ref_epoch
        )
        logger.info({"msg": f"All slashings with impact on midterm penalties: {len(all_slashed_validators)}"})

        # Put all Lido slashed validators to future frames by midterm penalty epoch
        future_frames_lido_validators = MidtermSlashingPenalty.get_lido_validators_with_future_midterm_epoch(
            blockstamp.ref_epoch, frame_config, lido_validators
        )

        # If no one Lido in current not withdrawn slashed validators
        # and no one midterm slashing epoch in the future - no need to bunker
        if not future_frames_lido_validators:
            return False

        # We should calculate total balance for each midterm penalty epoch and
        # make projection based on the current state of the chain
        total_balance = calculate_total_active_effective_balance(all_validators, blockstamp.ref_epoch)

        # Calculate sum of Lido midterm penalties in each future frame
        frames_lido_midterm_penalties = MidtermSlashingPenalty.get_future_midterm_penalty_sum_in_frames(
            blockstamp.ref_epoch, all_slashed_validators,  total_balance, future_frames_lido_validators,
        )
        max_lido_midterm_penalty = max(frames_lido_midterm_penalties.values())
        logger.info({"msg": f"Max lido midterm penalty: {max_lido_midterm_penalty}"})

        # Compare with calculated frame CL rebase on pessimistic strategy
        # and whether they will cover future midterm penalties, so that the bunker is better to be turned on than not
        frame_cl_rebase = MidtermSlashingPenalty.get_frame_cl_rebase_from_report_cl_rebase(
            frame_config, chain_config, current_report_cl_rebase, blockstamp, last_report_ref_slot
        )
        if max_lido_midterm_penalty > frame_cl_rebase:
            return True

        return False

    @staticmethod
    def get_slashed_validators_with_impact_on_midterm_penalties(
        validators: list[Validator],
        ref_epoch: EpochNumber
    ) -> list[Validator | LidoValidator]:
        """
        Get slashed validators which have impact on midterm penalties
        We can detect such slashings by this condition:
        `ref_epoch - EPOCHS_PER_SLASHINGS_VECTOR > possible_slashed_epoch > ref_epoch`
        But if we look at:
        https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#slash_validator
        it can be simplified to the condition above for our purposes
        """
        def is_have_impact(v: Validator) -> bool:
            return v.validator.slashed and int(v.validator.withdrawable_epoch) > ref_epoch

        return list(filter(is_have_impact, validators))

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

        earliest_possible_slashed_epoch = max(0, ref_epoch - EPOCHS_PER_SLASHINGS_VECTOR)
        # We get here `min` because exit queue can be greater than `EPOCHS_PER_SLASHINGS_VECTOR`
        # So possible slashed epoch can not be greater than `ref_epoch`
        latest_possible_epoch = min(ref_epoch, int(v.withdrawable_epoch) - EPOCHS_PER_SLASHINGS_VECTOR)
        return [EpochNumber(epoch) for epoch in range(earliest_possible_slashed_epoch, latest_possible_epoch + 1)]

    @staticmethod
    def get_lido_validators_with_future_midterm_epoch(
        ref_epoch: EpochNumber,
        frame_config: FrameConfig,
        lido_validators: list[LidoValidator],
    ) -> dict[FrameNumber, list[LidoValidator]]:
        """
        Put validators to frame buckets by their midterm penalty epoch to calculate penalties impact in each frame
        """
        buckets: dict[FrameNumber, list[LidoValidator]] = defaultdict(list[LidoValidator])
        for validator in lido_validators:
            if not validator.validator.slashed:
                # We need only slashed validators
                continue
            midterm_penalty_epoch = MidtermSlashingPenalty.get_midterm_penalty_epoch(validator)
            if midterm_penalty_epoch <= ref_epoch:
                # We need midterm penalties only from future frames
                continue
            frame_number = MidtermSlashingPenalty.get_frame_by_epoch(midterm_penalty_epoch, frame_config)
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
        midterm_penalized_validators_in_frame: list[LidoValidator]
    ) -> Gwei:
        """Predict penalty in frame"""
        penalty_in_frame = 0
        for validator in midterm_penalized_validators_in_frame:
            midterm_penalty_epoch = MidtermSlashingPenalty.get_midterm_penalty_epoch(validator)
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
        # We don't know which balance was at slashing epoch, so we make a pessimistic assumption that it was 32 ETH
        slashings = Gwei(bound_slashed_validators_count * MAX_EFFECTIVE_BALANCE)
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

        def is_bound(v: Validator) -> bool:
            possible_slashing_epochs = MidtermSlashingPenalty.get_possible_slashed_epochs(v, ref_epoch)
            return any(min_bound_epoch <= epoch <= midterm_penalty_epoch for epoch in possible_slashing_epochs)

        return list(filter(is_bound, slashed_validators))

    @staticmethod
    def get_frame_cl_rebase_from_report_cl_rebase(
        frame_config: FrameConfig,
        chain_config: ChainConfig,
        report_cl_rebase: Gwei,
        curr_report_blockstamp: ReferenceBlockStamp,
        last_report_ref_slot: SlotNumber
    ) -> Gwei:
        """Get frame rebase from report rebase"""
        last_report_ref_epoch = EpochNumber(last_report_ref_slot // chain_config.slots_per_epoch)

        epochs_passed_since_last_report = curr_report_blockstamp.ref_epoch - last_report_ref_epoch

        frame_cl_rebase = (
            (report_cl_rebase / epochs_passed_since_last_report) * frame_config.epochs_per_frame
        )
        return Gwei(int(frame_cl_rebase))

    @staticmethod
    def get_frame_by_epoch(epoch: EpochNumber, frame_config: FrameConfig) -> FrameNumber:
        """Get oracle report frame index by epoch"""
        return FrameNumber((epoch - frame_config.initial_epoch) // frame_config.epochs_per_frame)

    @staticmethod
    def get_midterm_penalty_epoch(validator: Validator) -> EpochNumber:
        """https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#slashings"""
        return EpochNumber(int(validator.validator.withdrawable_epoch) - EPOCHS_PER_SLASHINGS_VECTOR // 2)
