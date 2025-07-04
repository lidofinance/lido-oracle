import math
from typing import Iterable

from src.constants import EPOCHS_PER_SLASHINGS_VECTOR, MIN_VALIDATOR_WITHDRAWABILITY_DELAY
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.submodules.consensus import ChainConfig, FrameConfig
from src.types import EpochNumber, FrameNumber, ReferenceBlockStamp, SlotNumber
from src.utils.slot import get_blockstamp
from src.utils.web3converter import Web3Converter
from src.web3py.extensions.lido_validators import Validator
from src.web3py.types import Web3


class WrongExitPeriod(Exception):
    pass


class SafeBorder(Web3Converter):
    """
    Safe border service calculates the range in which withdrawal requests can't be finalized.

    In Turbo mode, there is only one border that does not allow to finalize requests created close to the reference
    slot to which the oracle report is performed.

    In Bunker mode there are more safe borders. The protocol takes into account the impact of negative factors
    that occurred in a certain period and finalizes requests on which the negative effects have already been socialized.

    There are 3 types of the border:
    1. Default border
    2. Negative rebase border
    3. Associated slashing border
    """
    chain_config: ChainConfig
    frame_config: FrameConfig
    blockstamp: ReferenceBlockStamp
    converter: Web3Converter

    def __init__(
        self,
        w3: Web3,
        blockstamp: ReferenceBlockStamp,
        chain_config: ChainConfig,
        frame_config: FrameConfig
    ) -> None:
        super().__init__(chain_config, frame_config)

        self.w3 = w3
        self.lido_contracts = w3.lido_contracts

        self.blockstamp = blockstamp
        self.chain_config = chain_config
        self.frame_config = frame_config

        self.converter = Web3Converter(chain_config, frame_config)
        self._retrieve_constants()

    def _retrieve_constants(self):
        limits_list = self.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits(self.blockstamp.block_hash)

        self.finalization_default_shift = math.ceil(
            limits_list.request_timestamp_margin / (self.chain_config.slots_per_epoch * self.chain_config.seconds_per_slot)
        )

    @duration_meter()
    def get_safe_border_epoch(
        self,
        is_bunker: bool,
    ) -> EpochNumber:
        if not is_bunker:
            return self._get_default_requests_border_epoch()

        negative_rebase_border_epoch = self._get_negative_rebase_border_epoch()
        associated_slashings_border_epoch = self._get_associated_slashings_border_epoch()

        return min(
            negative_rebase_border_epoch,
            associated_slashings_border_epoch,
        )

    def _get_default_requests_border_epoch(self) -> EpochNumber:
        """
        The default border is a few epochs before report reference epoch.
        """
        return EpochNumber(self.blockstamp.ref_epoch - self.finalization_default_shift)

    def _get_negative_rebase_border_epoch(self) -> EpochNumber:
        """
        Bunker mode can be enabled by a negative rebase in case of mass validator penalties.
        In this case the border is considered the reference slot of the previous successful oracle report before the
        moment the Bunker mode was activated - default border
        """
        bunker_start_or_last_successful_report_epoch = self._get_bunker_start_or_last_successful_report_epoch()

        latest_allowable_epoch = bunker_start_or_last_successful_report_epoch - self.finalization_default_shift

        max_negative_rebase = self.w3.lido_contracts.oracle_daemon_config.finalization_max_negative_rebase_epoch_shift(
            self.blockstamp.block_hash,
        )
        earliest_allowable_epoch = self.get_epoch_by_slot(self.blockstamp.ref_slot) - max_negative_rebase

        return EpochNumber(max(earliest_allowable_epoch, latest_allowable_epoch))

    def _get_bunker_start_or_last_successful_report_epoch(self) -> EpochNumber:
        bunker_start_timestamp = self._get_bunker_mode_start_timestamp()
        if bunker_start_timestamp is not None:
            return self.get_epoch_by_timestamp(bunker_start_timestamp)

        last_report_slot = self.w3.lido_contracts.get_accounting_last_processing_ref_slot(self.blockstamp)
        if last_report_slot != 0:
            return self.get_epoch_by_slot(last_report_slot)

        return EpochNumber(self.frame_config.initial_epoch)

    def _get_associated_slashings_border_epoch(self) -> EpochNumber:
        """
        The border represents the latest epoch before associated slashings started.

        It is calculated as the earliest slashed_epoch among all incompleted slashings at
        the point of reference_epoch rounded to the start of the previous oracle report frame - default border.

        See detailed research here: https://hackmd.io/@lido/r1Qkkiv3j
        """
        earliest_slashed_epoch = self._get_earliest_slashed_epoch_among_incomplete_slashings()

        if earliest_slashed_epoch:
            return EpochNumber(self.round_epoch_by_frame(earliest_slashed_epoch) - self.finalization_default_shift)

        return self._get_default_requests_border_epoch()

    @duration_meter()
    def _get_earliest_slashed_epoch_among_incomplete_slashings(self) -> EpochNumber | None:
        validators = self.w3.lido_validators.get_lido_validators(self.blockstamp)
        validators_slashed = filter_slashed_validators(validators)

        # Here we filter not by exit_epoch but by withdrawable_epoch because exited operators can still be slashed.
        # See more here https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#helpers
        # at `get_eligible_validator_indices` method.
        validators_slashed_non_withdrawable = filter_non_withdrawable_validators(validators_slashed, self.blockstamp.ref_epoch)

        if not validators_slashed_non_withdrawable:
            return None

        earliest_predicted_epoch = None
        for validator in validators_slashed_non_withdrawable:
            predicted_epoch = self._predict_earliest_slashed_epoch(validator)

            if not predicted_epoch:
                return self._find_earliest_slashed_epoch_rounded_to_frame(validators_slashed_non_withdrawable)

            if not earliest_predicted_epoch or earliest_predicted_epoch > predicted_epoch:
                earliest_predicted_epoch = predicted_epoch

        return earliest_predicted_epoch

    # The exit period for a specific validator may be equal to the MIN_VALIDATOR_WITHDRAWAL_DELAY.
    # This means that there are so many validators in the queue that the exit epoch moves with the withdrawable epoch,
    # and we cannot detect when slashing has started.
    def _predict_earliest_slashed_epoch(self, validator: Validator) -> EpochNumber | None:
        exit_epoch = validator.validator.exit_epoch
        withdrawable_epoch = validator.validator.withdrawable_epoch

        exited_period = withdrawable_epoch - exit_epoch

        if exited_period < MIN_VALIDATOR_WITHDRAWABILITY_DELAY:
            raise WrongExitPeriod("exit_epoch and withdrawable_epoch are too close")

        is_slashed_epoch_undetectable = exited_period == MIN_VALIDATOR_WITHDRAWABILITY_DELAY
        if is_slashed_epoch_undetectable:
            return None

        return EpochNumber(withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR)

    def _find_earliest_slashed_epoch_rounded_to_frame(self, validators: list[Validator]) -> EpochNumber:
        """
        Returns the earliest slashed epoch for the given validators rounded to the frame
        """
        last_finalized_request_id_epoch = self._get_last_finalized_withdrawal_request_epoch()
        earliest_activation_epoch = min((v.validator.activation_epoch for v in validators))
        # Since we are looking for the safe border epoch, we can start from the last finalized withdrawal request epoch
        # or the earliest activation epoch among the given validators for optimization
        start_epoch = max(last_finalized_request_id_epoch, earliest_activation_epoch)

        # We can stop searching for the slashed epoch when we reach the reference epoch
        # or the max possible earliest slashed epoch for the given validators
        withdrawable_epoch = min(v.validator.withdrawable_epoch for v in validators)
        max_possible_earliest_slashed_epoch = EpochNumber(withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR)
        end_epoch = min(self.blockstamp.ref_epoch, max_possible_earliest_slashed_epoch)

        start_frame = self.get_frame_by_epoch(EpochNumber(start_epoch))
        end_frame = self.get_frame_by_epoch(EpochNumber(end_epoch))

        slashed_pubkeys = set(v.validator.pubkey for v in validators)

        # Since the border will be rounded to the frame, we are iterating over the frames
        # to avoid unnecessary queries
        while start_frame < end_frame:
            mid_frame = FrameNumber((end_frame + start_frame) // 2)

            if self._slashings_in_frame(mid_frame, slashed_pubkeys):
                end_frame = mid_frame
            else:
                start_frame = FrameNumber(mid_frame + 1)

        slot_number = self.get_frame_first_slot(start_frame)
        epoch_number = self.get_epoch_by_slot(slot_number)
        return epoch_number

    def _slashings_in_frame(self, frame: FrameNumber, slashed_pubkeys: set[str]) -> bool:
        """
        Returns number of slashed validators for the frame for the given validators
        Slashed flag can't be undone, so we can only look at the last slot
        """
        last_slot_in_frame = self.get_frame_last_slot(frame)
        last_slot_in_frame_blockstamp = self._get_blockstamp(last_slot_in_frame)

        lido_validators = self.w3.lido_validators.get_lido_validators(last_slot_in_frame_blockstamp)
        slashed_validators = filter_slashed_validators(
            v for v in lido_validators if v.validator.pubkey in slashed_pubkeys
        )

        return len(slashed_validators) > 0

    def _get_bunker_mode_start_timestamp(self) -> int | None:
        start_timestamp = self.w3.lido_contracts.withdrawal_queue_nft.bunker_mode_since_timestamp(self.blockstamp.block_hash)

        if start_timestamp > self.blockstamp.block_timestamp:
            return None

        return start_timestamp

    def _get_last_finalized_withdrawal_request_epoch(self) -> EpochNumber:
        last_finalized_request_id = self.w3.lido_contracts.withdrawal_queue_nft.get_last_finalized_request_id(self.blockstamp.block_hash)
        if last_finalized_request_id == 0:
            # request with id: 0 is reserved by protocol. No requests were finalized.
            return EpochNumber(0)

        last_finalized_request_data = self.w3.lido_contracts.withdrawal_queue_nft.get_withdrawal_status(last_finalized_request_id)

        return self.get_epoch_by_timestamp(last_finalized_request_data.timestamp)

    def _get_blockstamp(self, last_slot_in_frame: SlotNumber):
        return get_blockstamp(self.w3.cc, last_slot_in_frame, self.blockstamp.ref_slot)

    def round_epoch_by_frame(self, epoch: EpochNumber) -> EpochNumber:
        return EpochNumber(
            self.get_frame_by_epoch(epoch) * self.frame_config.epochs_per_frame + self.frame_config.initial_epoch)


def filter_slashed_validators(validators: Iterable[Validator]) -> list[Validator]:
    return [v for v in validators if v.validator.slashed]


def filter_non_withdrawable_validators(slashed_validators: Iterable[Validator], epoch: EpochNumber) -> list[Validator]:
    # This filter works only with slashed_validators
    return [v for v in slashed_validators if v.validator.withdrawable_epoch > epoch]
