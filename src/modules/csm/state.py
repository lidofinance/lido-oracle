import logging
import os
import pickle
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import batched
from pathlib import Path
from typing import Self

from src import variables
from src.constants import CSM_STATE_VERSION
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
    attestations: defaultdict[ValidatorIndex, DutyAccumulator] = field(default_factory=lambda: defaultdict(DutyAccumulator))
    proposals: defaultdict[ValidatorIndex, DutyAccumulator] = field(default_factory=lambda: defaultdict(DutyAccumulator))
    syncs: defaultdict[ValidatorIndex, DutyAccumulator] = field(default_factory=lambda: defaultdict(DutyAccumulator))

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
    # pylint: disable=too-many-public-methods

    """
    Processing state of a CSM performance oracle frame.

    During the CSM module startup the state object is being either `load`'ed from the filesystem or being created as a
    new object with no data in it. During epochs processing aggregates in `data` are being updated and eventually the
    state is `commit`'ed back to the filesystem.

    The state can be migrated to be used for another frame's report by calling the `migrate` method.
    """

    data: StateData

    _epochs_to_process: tuple[EpochNumber, ...]
    _processed_epochs: set[EpochNumber]

    _version: int

    EXTENSION = ".pkl"

    def __init__(self) -> None:
        self.data = {}
        self._epochs_to_process = tuple()
        self._processed_epochs = set()
        self._version = CSM_STATE_VERSION

    @property
    def version(self) -> int | None:
        return getattr(self, "_version", None)

    @classmethod
    def load(cls) -> Self:
        """Used to restore the object from the persistent storage"""

        obj: Self | None = None
        file = cls.file()
        try:
            with file.open(mode="rb") as f:
                obj = pickle.load(f)
                print({"msg": "Read object from pickle file"})
                if not obj:
                    raise ValueError("Got empty object")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.info({"msg": f"Unable to restore {cls.__name__} instance from {file.absolute()}", "error": str(e)})
        else:
            logger.info({"msg": f"{cls.__name__} read from {file.absolute()}"})
        return obj or cls()

    def commit(self) -> None:
        with self.buffer.open(mode="wb") as f:
            pickle.dump(self, f)

        os.replace(self.buffer, self.file())

    @classmethod
    def file(cls) -> Path:
        return variables.CACHE_PATH / Path("cache").with_suffix(cls.EXTENSION)

    @property
    def buffer(self) -> Path:
        return self.file().with_suffix(".buf")

    @property
    def is_empty(self) -> bool:
        return not self.data and not self._epochs_to_process and not self._processed_epochs

    @property
    def frames(self) -> list[Frame]:
        return list(self.data.keys())

    @property
    def unprocessed_epochs(self) -> set[EpochNumber]:
        if not self._epochs_to_process:
            raise ValueError("Epochs to process are not set")
        diff = set(self._epochs_to_process) - self._processed_epochs
        return diff

    @property
    def is_fulfilled(self) -> bool:
        return not self.unprocessed_epochs

    @staticmethod
    def _calculate_frames(epochs_to_process: tuple[EpochNumber, ...], epochs_per_frame: int) -> list[Frame]:
        """Split epochs to process into frames of `epochs_per_frame` length"""
        if len(epochs_to_process) % epochs_per_frame != 0:
            raise ValueError("Insufficient epochs to form a frame")
        return [(frame[0], frame[-1]) for frame in batched(sorted(epochs_to_process), epochs_per_frame)]

    def clear(self) -> None:
        self.data = {}
        self._epochs_to_process = tuple()
        self._processed_epochs.clear()
        assert self.is_empty

    @lru_cache(variables.CSM_ORACLE_MAX_CONCURRENCY)
    def find_frame(self, epoch: EpochNumber) -> Frame:
        for epoch_range in self.frames:
            from_epoch, to_epoch = epoch_range
            if from_epoch <= epoch <= to_epoch:
                return epoch_range
        raise ValueError(f"Epoch {epoch} is out of frames range: {self.frames}")

    def save_att_duty(self, epoch: EpochNumber, val_index: ValidatorIndex, included: bool) -> None:
        frame = self.find_frame(epoch)
        self.data[frame].attestations[val_index].add_duty(included)

    def save_prop_duty(self, epoch: EpochNumber, val_index: ValidatorIndex, included: bool) -> None:
        frame = self.find_frame(epoch)
        self.data[frame].proposals[val_index].add_duty(included)

    def save_sync_duty(self, epoch: EpochNumber, val_index: ValidatorIndex, included: bool) -> None:
        frame = self.find_frame(epoch)
        self.data[frame].syncs[val_index].add_duty(included)

    def add_processed_epoch(self, epoch: EpochNumber) -> None:
        self._processed_epochs.add(epoch)

    def log_progress(self) -> None:
        logger.info({"msg": f"Processed {len(self._processed_epochs)} of {len(self._epochs_to_process)} epochs"})

    def migrate(self, l_epoch: EpochNumber, r_epoch: EpochNumber, epochs_per_frame: int) -> None:
        if self.version != CSM_STATE_VERSION:
            if self.version is not None:
                logger.warning(
                    {
                        "msg": f"Cache was built with version={self.version}. "
                        f"Discarding data to migrate to cache version={CSM_STATE_VERSION}"
                    }
                )
            self.clear()

        new_frames = self._calculate_frames(tuple(sequence(l_epoch, r_epoch)), epochs_per_frame)
        if self.frames == new_frames:
            logger.info({"msg": "No need to migrate duties data cache"})
            return
        self._migrate_frames_data(new_frames)

        self.find_frame.cache_clear()
        self._epochs_to_process = tuple(sequence(l_epoch, r_epoch))
        self._version = CSM_STATE_VERSION
        self.commit()

    def _migrate_frames_data(self, new_frames: list[Frame]):
        logger.info({"msg": f"Migrating duties data cache: {self.frames=} -> {new_frames=}"})
        new_data: StateData = {}
        for frame in new_frames:
            new_data[frame] = NetworkDuties()

        def overlaps(a: Frame, b: Frame):
            return a[0] <= b[0] and a[1] >= b[1]

        consumed = []
        for new_frame in new_frames:
            for frame_to_consume in self.frames:
                if overlaps(new_frame, frame_to_consume):
                    assert frame_to_consume not in consumed
                    consumed.append(frame_to_consume)
                    new_data[new_frame].merge(self.data[frame_to_consume])
        for frame in self.frames:
            if frame in consumed:
                continue
            logger.warning({"msg": f"Invalidating frame duties data cache: {frame}"})
            self._processed_epochs -= set(sequence(*frame))
        self.data = new_data

    def validate(self, l_epoch: EpochNumber, r_epoch: EpochNumber) -> None:
        if not self.is_fulfilled:
            raise InvalidState(f"State is not fulfilled. {self.unprocessed_epochs=}")

        for epoch in self._processed_epochs:
            if not l_epoch <= epoch <= r_epoch:
                raise InvalidState(f"Processed epoch {epoch} is out of range")

        for epoch in sequence(l_epoch, r_epoch):
            if epoch not in self._processed_epochs:
                raise InvalidState(f"Epoch {epoch} missing in processed epochs")

    def get_validator_duties(self, frame: Frame, validator_index: ValidatorIndex) -> ValidatorDuties:
        frame_data = self.data.get(frame)
        if frame_data is None:
            raise ValueError(f"No data for frame: {frame=}")

        att_duty = frame_data.attestations.get(validator_index)
        prop_duty = frame_data.proposals.get(validator_index)
        sync_duty = frame_data.syncs.get(validator_index)

        return ValidatorDuties(att_duty, prop_duty, sync_duty)

    def get_att_network_aggr(self, frame: Frame) -> DutyAccumulator:
        # TODO: exclude `active_slashed` validators from the calculation
        frame_data = self.data.get(frame)
        if frame_data is None:
            raise ValueError(f"No data for frame: {frame=}")
        aggr = self._get_duty_network_aggr(frame_data.attestations)
        logger.info({"msg": "Network attestations aggregate computed", "value": repr(aggr), "avg_perf": aggr.perf})
        return aggr

    def get_prop_network_aggr(self, frame: Frame) -> DutyAccumulator:
        frame_data = self.data.get(frame)
        if frame_data is None:
            raise ValueError(f"No data for frame: {frame=}")
        aggr = self._get_duty_network_aggr(frame_data.proposals)
        logger.info({"msg": "Network proposal aggregate computed", "value": repr(aggr), "avg_perf": aggr.perf})
        return aggr

    def get_sync_network_aggr(self, frame: Frame) -> DutyAccumulator:
        frame_data = self.data.get(frame)
        if frame_data is None:
            raise ValueError(f"No data for frame: {frame=}")
        aggr = self._get_duty_network_aggr(frame_data.syncs)
        logger.info({"msg": "Network syncs aggregate computed", "value": repr(aggr), "avg_perf": aggr.perf})
        return aggr

    @staticmethod
    def _get_duty_network_aggr(duty_frame_data: defaultdict[ValidatorIndex, DutyAccumulator]) -> DutyAccumulator:
        included = assigned = 0
        for validator, acc in duty_frame_data.items():
            if acc.included > acc.assigned:
                raise ValueError(f"Invalid accumulator: {validator=}, {acc=}")
            included += acc.included
            assigned += acc.assigned
        aggr = DutyAccumulator(
            included=included,
            assigned=assigned,
        )
        return aggr
