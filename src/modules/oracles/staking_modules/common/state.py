import logging
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import batched
from typing import Self

from src.types import EpochNumber, ValidatorIndex
from src.utils.range import sequence


logger = logging.getLogger(__name__)


class InvalidState(ValueError):
    """State has data considered as invalid for a report"""


@dataclass
class DutyAccumulator:
    """Accumulator of duties observed for a validator"""

    assigned: int = 0
    included: int = 0

    @property
    def perf(self) -> float:
        return self.included / self.assigned if self.assigned else 0

    def add_duty(self, included: bool) -> None:
        self.assigned += 1
        self.included += 1 if included else 0

    def merge(self, other: Self) -> None:
        self.assigned += other.assigned
        self.included += other.included


@dataclass
class ValidatorDuties:
    attestation: DutyAccumulator | None
    proposal: DutyAccumulator | None
    sync: DutyAccumulator | None


@dataclass
class NetworkDuties:
    # fmt: off
    attestations: defaultdict[ValidatorIndex, DutyAccumulator] = field(
        default_factory=lambda: defaultdict(DutyAccumulator)
    )
    proposals: defaultdict[ValidatorIndex, DutyAccumulator] = field(
        default_factory=lambda: defaultdict(DutyAccumulator)
    )
    syncs: defaultdict[ValidatorIndex, DutyAccumulator] = field(
        default_factory=lambda: defaultdict(DutyAccumulator)
    )

    def merge(self, other: Self) -> None:
        for val, duty in other.attestations.items():
            self.attestations[val].merge(duty)
        for val, duty in other.proposals.items():
            self.proposals[val].merge(duty)
        for val, duty in other.syncs.items():
            self.syncs[val].merge(duty)


type Frame = tuple[EpochNumber, EpochNumber]
type StateData = dict[Frame, NetworkDuties]


class State:
    """Processing state of a staking module performance oracle frame"""

    data: StateData
    is_fulfilled: bool

    def __init__(self, l_epoch: EpochNumber, r_epoch: EpochNumber, epochs_per_frame: int) -> None:
        frames = self._calculate_frames(tuple(sequence(l_epoch, r_epoch)), epochs_per_frame)
        logger.info({"msg": f"Initializing state: {frames=}"})
        data: StateData = {}
        for frame in frames:
            data[frame] = NetworkDuties()
        self.data = data
        self.is_fulfilled = False

    @property
    def frames(self) -> list[Frame]:
        return list(self.data.keys())

    @staticmethod
    def _calculate_frames(epochs_to_process: tuple[EpochNumber, ...], epochs_per_frame: int) -> list[Frame]:
        """Split epochs to process into frames of `epochs_per_frame` length"""
        if len(epochs_to_process) % epochs_per_frame != 0:
            raise ValueError("Insufficient epochs to form a frame")
        return [(frame[0], frame[-1]) for frame in batched(sorted(epochs_to_process), epochs_per_frame, strict=False)]

    def save_duties(self, frame: Frame, data: NetworkDuties) -> None:
        frame_data = self.data.get(frame)
        if frame_data is None:
            raise InvalidState(f"No data for frame: {frame=}")
        frame_data.merge(data)

    def get_validator_duties(self, frame: Frame, validator_index: ValidatorIndex) -> ValidatorDuties:
        frame_data = self.data.get(frame)
        if frame_data is None:
            raise InvalidState(f"No data for frame: {frame=}")

        att_duty = frame_data.attestations.get(validator_index)
        prop_duty = frame_data.proposals.get(validator_index)
        sync_duty = frame_data.syncs.get(validator_index)

        return ValidatorDuties(att_duty, prop_duty, sync_duty)

    def get_att_network_aggr(self, frame: Frame) -> DutyAccumulator:
        # TODO: exclude `active_slashed` validators from the calculation
        frame_data = self.data.get(frame)
        if frame_data is None:
            raise InvalidState(f"No data for frame: {frame=}")
        aggr = self._get_duty_network_aggr(frame_data.attestations)
        logger.info({"msg": "Network attestations aggregate computed", "value": repr(aggr), "avg_perf": aggr.perf})
        return aggr

    def get_prop_network_aggr(self, frame: Frame) -> DutyAccumulator:
        frame_data = self.data.get(frame)
        if frame_data is None:
            raise InvalidState(f"No data for frame: {frame=}")
        aggr = self._get_duty_network_aggr(frame_data.proposals)
        logger.info({"msg": "Network proposal aggregate computed", "value": repr(aggr), "avg_perf": aggr.perf})
        return aggr

    def get_sync_network_aggr(self, frame: Frame) -> DutyAccumulator:
        frame_data = self.data.get(frame)
        if frame_data is None:
            raise InvalidState(f"No data for frame: {frame=}")
        aggr = self._get_duty_network_aggr(frame_data.syncs)
        logger.info({"msg": "Network syncs aggregate computed", "value": repr(aggr), "avg_perf": aggr.perf})
        return aggr

    @staticmethod
    def _get_duty_network_aggr(duty_frame_data: defaultdict[ValidatorIndex, DutyAccumulator]) -> DutyAccumulator:
        included = assigned = 0
        for validator, acc in duty_frame_data.items():
            if acc.included > acc.assigned:
                raise InvalidState(f"Invalid accumulator: {validator=}, {acc=}")
            included += acc.included
            assigned += acc.assigned
        aggr = DutyAccumulator(
            included=included,
            assigned=assigned,
        )
        return aggr
