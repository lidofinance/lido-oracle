import logging
from collections import defaultdict
from typing import Callable

from src.constants import (
    EFFECTIVE_BALANCE_INCREMENT,
    EPOCHS_PER_SLASHINGS_VECTOR,
    MAX_EFFECTIVE_BALANCE,
    MIN_VALIDATOR_WITHDRAWABILITY_DELAY,
    PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX,
)
from src.providers.consensus.types import Validator
from src.types import EpochNumber, FrameNumber, Gwei, ReferenceBlockStamp, SlotNumber
from src.utils.validator_state import calculate_total_active_effective_balance
from src.utils.web3converter import Web3Converter
from src.web3py.extensions.lido_validators import LidoValidator

logger = logging.getLogger(__name__)

type SlashedValidatorsFrameBuckets = dict[tuple[FrameNumber, EpochNumber], list[LidoValidator]]


class MidtermSlashingPenalty:
    @staticmethod
    def is_high_midterm_slashing_penalty(
        blockstamp: ReferenceBlockStamp,
        consensus_version: int,
        is_electra_activated: Callable[[EpochNumber], bool],
        web3_converter: Web3Converter,
        all_validators: list[Validator],
        lido_validators: list[LidoValidator],
        slashings: list[Gwei],
        current_report_cl_rebase: Gwei,
        last_report_ref_slot: SlotNumber,
    ) -> bool:
        """
        Check if there is a high midterm slashing penalty in the future frames.

        If current report CL rebase contains more than one frame, we should calculate the CL rebase for only one frame
        and compare max midterm penalty with calculated for one frame CL rebase
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
            blockstamp.ref_epoch, web3_converter, lido_validators
        )

        # If no one Lido in current not withdrawn slashed validators
        # and no one midterm slashing epoch in the future - no need to bunker
        if not future_frames_lido_validators:
            return False

        # We should calculate total balance for each midterm penalty epoch and
        # make projection based on the current state of the chain
        total_balance = calculate_total_active_effective_balance(all_validators, blockstamp.ref_epoch)

        # Calculate sum of Lido midterm penalties in each future frame
        if consensus_version < 3:
            frames_lido_midterm_penalties = MidtermSlashingPenalty.get_future_midterm_penalty_sum_in_frames_pre_electra(
                blockstamp.ref_epoch, all_slashed_validators, total_balance, future_frames_lido_validators
            )
        else:
            frames_lido_midterm_penalties = (
                MidtermSlashingPenalty.get_future_midterm_penalty_sum_in_frames_post_electra(
                    blockstamp.ref_epoch,
                    is_electra_activated,
                    all_slashed_validators,
                    slashings,
                    total_balance,
                    future_frames_lido_validators,
                )
            )
        max_lido_midterm_penalty = max(frames_lido_midterm_penalties.values())
        logger.info({"msg": f"Max lido midterm penalty: {max_lido_midterm_penalty}"})

        # Compare with calculated frame CL rebase on pessimistic strategy
        # and whether they will cover future midterm penalties, so that the bunker is better to be turned on than not
        frame_cl_rebase = MidtermSlashingPenalty.get_frame_cl_rebase_from_report_cl_rebase(
            web3_converter, current_report_cl_rebase, blockstamp, last_report_ref_slot
        )
        if max_lido_midterm_penalty > frame_cl_rebase:
            return True

        return False

    @staticmethod
    def get_slashed_validators_with_impact_on_midterm_penalties(
        validators: list[Validator], ref_epoch: EpochNumber
    ) -> list[Validator]:
        """
        Get slashed validators which have impact on midterm penalties

        The original condition by which we filter validators is as follows:
        ref_epoch - EPOCHS_PER_SLASHINGS_VECTOR < latest_possible_slashed_epoch <= ref_epoch

        But could be simplified to: ref_epoch < withdrawable_epoch

        1) ref_epoch - EPOCHS_PER_SLASHINGS_VECTOR < latest_possible_slashed_epoch
           since slashed epoch couldn't be in the future

        2) latest_possible_slashed_epoch = withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR
        ref_epoch - EPOCHS_PER_SLASHINGS_VECTOR < withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR
        ref_epoch < withdrawable_epoch

        https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#slash_validator
        """

        def is_have_impact(v: Validator) -> bool:
            return v.validator.slashed and v.validator.withdrawable_epoch > ref_epoch

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

        if v.withdrawable_epoch - v.exit_epoch > MIN_VALIDATOR_WITHDRAWABILITY_DELAY:
            determined_slashed_epoch = EpochNumber(v.withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR)
            return [determined_slashed_epoch]

        earliest_possible_slashed_epoch = max(0, ref_epoch - EPOCHS_PER_SLASHINGS_VECTOR)
        # We get here `min` because exit queue can be greater than `EPOCHS_PER_SLASHINGS_VECTOR`
        # So possible slashed epoch can not be greater than `ref_epoch`
        latest_possible_epoch = min(ref_epoch, v.withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR)
        return [EpochNumber(epoch) for epoch in range(earliest_possible_slashed_epoch, latest_possible_epoch + 1)]

    @staticmethod
    def get_lido_validators_with_future_midterm_epoch(
        ref_epoch: EpochNumber,
        web3_converter: Web3Converter,
        lido_validators: list[LidoValidator],
    ) -> SlashedValidatorsFrameBuckets:
        """
        Put validators to frame buckets by their midterm penalty epoch to calculate penalties impact in each frame
        """
        buckets: SlashedValidatorsFrameBuckets = defaultdict(list[LidoValidator])
        for validator in lido_validators:
            if not validator.validator.slashed:
                # We need only slashed validators
                continue
            midterm_penalty_epoch = MidtermSlashingPenalty.get_midterm_penalty_epoch(validator)
            if midterm_penalty_epoch <= ref_epoch:
                # We need midterm penalties only from future frames
                continue
            frame_number = web3_converter.get_frame_by_epoch(midterm_penalty_epoch)
            frame_ref_slot = SlotNumber(web3_converter.get_frame_first_slot(frame_number) - 1)
            frame_ref_epoch = web3_converter.get_epoch_by_slot(frame_ref_slot)
            buckets[(frame_number, frame_ref_epoch)].append(validator)

        return buckets

    @staticmethod
    def get_future_midterm_penalty_sum_in_frames_pre_electra(
        ref_epoch: EpochNumber,
        all_slashed_validators: list[Validator],
        total_balance: Gwei,
        per_frame_validators: SlashedValidatorsFrameBuckets,
    ) -> dict[FrameNumber, Gwei]:
        """Calculate sum of midterm penalties in each frame"""
        per_frame_midterm_penalty_sum: dict[FrameNumber, Gwei] = {}
        for (frame_number, _), validators_in_future_frame in per_frame_validators.items():
            per_frame_midterm_penalty_sum[frame_number] = (
                MidtermSlashingPenalty.predict_midterm_penalty_in_frame_pre_electra(
                    ref_epoch, all_slashed_validators, total_balance, validators_in_future_frame
                )
            )

        return per_frame_midterm_penalty_sum

    @staticmethod
    def predict_midterm_penalty_in_frame_pre_electra(
        ref_epoch: EpochNumber,
        all_slashed_validators: list[Validator],
        total_balance: Gwei,
        midterm_penalized_validators_in_frame: list[LidoValidator],
    ) -> Gwei:
        """Predict penalty in frame"""
        penalty_in_frame = 0
        for validator in midterm_penalized_validators_in_frame:
            midterm_penalty_epoch = MidtermSlashingPenalty.get_midterm_penalty_epoch(validator)
            bound_slashed_validators = MidtermSlashingPenalty.get_bound_with_midterm_epoch_slashed_validators(
                ref_epoch, all_slashed_validators, midterm_penalty_epoch
            )
            penalty_in_frame += MidtermSlashingPenalty.get_validator_midterm_penalty(
                validator, len(bound_slashed_validators), total_balance
            )
        return Gwei(penalty_in_frame)

    @staticmethod
    def get_future_midterm_penalty_sum_in_frames_post_electra(
        ref_epoch: EpochNumber,
        is_electra_activated: Callable[[EpochNumber], bool],
        all_slashed_validators: list[Validator],
        slashings: list[Gwei],
        total_balance: Gwei,
        per_frame_validators: SlashedValidatorsFrameBuckets,
    ) -> dict[FrameNumber, Gwei]:
        """Calculate sum of midterm penalties in each frame"""
        per_frame_midterm_penalty_sum: dict[FrameNumber, Gwei] = {}
        for (frame_number, frame_ref_epoch), validators_in_future_frame in per_frame_validators.items():
            per_frame_midterm_penalty_sum[frame_number] = (
                MidtermSlashingPenalty.predict_midterm_penalty_in_frame_post_electra(
                    ref_epoch,
                    frame_ref_epoch,
                    is_electra_activated,
                    all_slashed_validators,
                    slashings,
                    total_balance,
                    validators_in_future_frame,
                )
            )

        return per_frame_midterm_penalty_sum

    @staticmethod
    def predict_midterm_penalty_in_frame_post_electra(
        report_ref_epoch: EpochNumber,
        frame_ref_epoch: EpochNumber,
        is_electra_activated: Callable[[EpochNumber], bool],
        all_slashed_validators: list[Validator],
        slashings: list[Gwei],
        total_balance: Gwei,
        midterm_penalized_validators_in_frame: list[LidoValidator],
    ) -> Gwei:
        """Predict penalty in frame"""
        penalty_in_frame = 0
        for validator in midterm_penalized_validators_in_frame:
            midterm_penalty_epoch = MidtermSlashingPenalty.get_midterm_penalty_epoch(validator)
            # all validators which were slashed in [midterm_penalty_epoch - EPOCHS_PER_SLASHINGS_VECTOR, midterm_penalty_epoch]
            bound_slashed_validators = MidtermSlashingPenalty.get_bound_with_midterm_epoch_slashed_validators(
                report_ref_epoch, all_slashed_validators, midterm_penalty_epoch
            )

            if is_electra_activated(frame_ref_epoch):
                penalty_in_frame += MidtermSlashingPenalty.get_validator_midterm_penalty_electra(
                    validator, slashings, total_balance, midterm_penalty_epoch, report_ref_epoch
                )
            else:
                penalty_in_frame += MidtermSlashingPenalty.get_validator_midterm_penalty(
                    validator, len(bound_slashed_validators), total_balance
                )
        return Gwei(penalty_in_frame)

    @staticmethod
    def get_validator_midterm_penalty(
        validator: LidoValidator,
        bound_slashed_validators_count: int,
        total_balance: Gwei,
    ) -> Gwei:
        """
        Calculate midterm penalty for particular validator
        https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#slashings
        """
        # We don't know which balance was at slashing epoch, so we make a pessimistic assumption that it was 32 ETH
        slashings = Gwei(bound_slashed_validators_count * MAX_EFFECTIVE_BALANCE)
        adjusted_total_slashing_balance = min(slashings * PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX, total_balance)
        effective_balance = validator.validator.effective_balance
        penalty_numerator = effective_balance // EFFECTIVE_BALANCE_INCREMENT * adjusted_total_slashing_balance
        penalty = penalty_numerator // total_balance * EFFECTIVE_BALANCE_INCREMENT

        return Gwei(penalty)

    @staticmethod
    def get_validator_midterm_penalty_electra(
        validator: LidoValidator,
        slashings: list[Gwei],
        total_balance: Gwei,
        midterm_penalty_epoch: EpochNumber,
        report_ref_epoch: EpochNumber
    ) -> Gwei:
        """
        Calculate midterm penalty for particular validator
        https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#modified-process_slashings
        """
        slashings = sum(MidtermSlashingPenalty._cut_slashings(slashings, midterm_penalty_epoch, report_ref_epoch))
        adjusted_total_slashing_balance = min(
            slashings * PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX,
            total_balance,
        )
        effective_balance = validator.validator.effective_balance
        increment = EFFECTIVE_BALANCE_INCREMENT
        penalty_per_effective_balance_increment = adjusted_total_slashing_balance // (total_balance // increment)
        effective_balance_increments = effective_balance // increment
        penalty = penalty_per_effective_balance_increment * effective_balance_increments
        return Gwei(penalty)

    @staticmethod
    def _cut_slashings(
        slashings: list[Gwei], midterm_penalty_epoch: EpochNumber, report_ref_epoch: EpochNumber
    ) -> list[Gwei]:
        """
        Filters out slashing values based on epochs within a midterm penalty epoch. Slashings is a ring buffer on epochs.
        @see https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#modified-slash_validator
        We want to filter out epochs in the past which will not be relevant at the time of midterm penalty epoch.

        :param slashings: List of slashing values.
        :param midterm_penalty_epoch: The epoch defining the left bound.
        :param report_ref_epoch: The reference epoch for filtering.
        :return: Filtered list of slashing values.
        """
        skip_indexes = {
            i % EPOCHS_PER_SLASHINGS_VECTOR for i in range(midterm_penalty_epoch - EPOCHS_PER_SLASHINGS_VECTOR, report_ref_epoch)
        }
        return [slashings[i] for i in skip_indexes if i < len(slashings)]

    @staticmethod
    def get_bound_with_midterm_epoch_slashed_validators(
        ref_epoch: EpochNumber,
        slashed_validators: list[Validator],
        midterm_penalty_epoch: EpochNumber,
    ) -> list[Validator]:
        """
        Get bounded slashed validators for particular epoch
        All slashings that happened in the nearest EPOCHS_PER_SLASHINGS_VECTOR ago from a midterm penalty epoch considered as bounded
        """
        min_bound_epoch = max(0, midterm_penalty_epoch - EPOCHS_PER_SLASHINGS_VECTOR)

        def is_bound(v: Validator) -> bool:
            possible_slashing_epochs = MidtermSlashingPenalty.get_possible_slashed_epochs(v, ref_epoch)
            return any(min_bound_epoch <= epoch <= midterm_penalty_epoch for epoch in possible_slashing_epochs)

        return [v for v in slashed_validators if is_bound(v)]

    @staticmethod
    def get_frame_cl_rebase_from_report_cl_rebase(
        web3_converter: Web3Converter,
        report_cl_rebase: Gwei,
        curr_report_blockstamp: ReferenceBlockStamp,
        last_report_ref_slot: SlotNumber,
    ) -> Gwei:
        """Get frame rebase from report rebase"""
        last_report_ref_epoch = web3_converter.get_epoch_by_slot(last_report_ref_slot)

        epochs_passed_since_last_report = curr_report_blockstamp.ref_epoch - last_report_ref_epoch

        frame_cl_rebase = int(
            (report_cl_rebase / epochs_passed_since_last_report) * web3_converter.frame_config.epochs_per_frame
        )
        return Gwei(frame_cl_rebase)

    @staticmethod
    def get_midterm_penalty_epoch(validator: Validator) -> EpochNumber:
        """https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#slashings"""
        return EpochNumber(validator.validator.withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR // 2)
