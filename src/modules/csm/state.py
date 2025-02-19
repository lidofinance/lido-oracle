import logging
import os
import pickle
from collections import defaultdict
from dataclasses import dataclass
from itertools import batched
from pathlib import Path
from typing import Self

from src import variables
from src.types import EpochNumber, ValidatorIndex
from src.utils.range import sequence

logger = logging.getLogger(__name__)


class InvalidState(ValueError):
    """State has data considered as invalid for a report"""


@dataclass
class AttestationsAccumulator:
    """Accumulator of attestations duties observed for a validator"""

    assigned: int = 0
    included: int = 0

    @property
    def perf(self) -> float:
        return self.included / self.assigned if self.assigned else 0

    def add_duty(self, included: bool) -> None:
        self.assigned += 1
        self.included += 1 if included else 0


type Frame = tuple[EpochNumber, EpochNumber]
type StateData = dict[Frame, defaultdict[ValidatorIndex, AttestationsAccumulator]]


class State:
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
    _epochs_per_frame: int

    _consensus_version: int = 1

    def __init__(self) -> None:
        self.data = {}
        self._epochs_to_process = tuple()
        self._processed_epochs = set()
        self._epochs_per_frame = 0

    EXTENSION = ".pkl"

    @classmethod
    def load(cls) -> Self:
        """Used to restore the object from the persistent storage"""

        obj: Self | None = None
        file = cls.file()
        try:
            with file.open(mode="rb") as f:
                obj = pickle.load(f)
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
    def unprocessed_epochs(self) -> set[EpochNumber]:
        if not self._epochs_to_process:
            raise ValueError("Epochs to process are not set")
        diff = set(self._epochs_to_process) - self._processed_epochs
        return diff

    @property
    def is_fulfilled(self) -> bool:
        return not self.unprocessed_epochs

    @property
    def frames(self):
        return self._calculate_frames(self._epochs_to_process, self._epochs_per_frame)

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

    def find_frame(self, epoch: EpochNumber) -> Frame:
        for epoch_range in self.frames:
            if epoch_range[0] <= epoch <= epoch_range[1]:
                return epoch_range
        raise ValueError(f"Epoch {epoch} is out of frames range: {self.frames}")

    def increment_duty(self, frame: Frame, val_index: ValidatorIndex, included: bool) -> None:
        if frame not in self.data:
            raise ValueError(f"Frame {frame} is not found in the state")
        self.data[frame][val_index].add_duty(included)

    def add_processed_epoch(self, epoch: EpochNumber) -> None:
        self._processed_epochs.add(epoch)

    def log_progress(self) -> None:
        logger.info({"msg": f"Processed {len(self._processed_epochs)} of {len(self._epochs_to_process)} epochs"})

    def init_or_migrate(
        self, l_epoch: EpochNumber, r_epoch: EpochNumber, epochs_per_frame: int, consensus_version: int
    ) -> None:
        if consensus_version != self._consensus_version:
            logger.warning(
                {
                    "msg": f"Cache was built for consensus version {self._consensus_version}. "
                    f"Discarding data to migrate to consensus version {consensus_version}"
                }
            )
            self.clear()

        frames = self._calculate_frames(tuple(sequence(l_epoch, r_epoch)), epochs_per_frame)
        frames_data: StateData = {frame: defaultdict(AttestationsAccumulator) for frame in frames}

        if not self.is_empty:
            cached_frames = self.frames
            if cached_frames == frames:
                logger.info({"msg": "No need to migrate duties data cache"})
                return

            frames_data, migration_status = self._migrate_frames_data(cached_frames, frames)

            for current_frame, migrated in migration_status.items():
                if not migrated:
                    logger.warning({"msg": f"Invalidating frame duties data cache: {current_frame}"})
                    self._processed_epochs.difference_update(sequence(*current_frame))

        self.data = frames_data
        self._epochs_per_frame = epochs_per_frame
        self._epochs_to_process = tuple(sequence(l_epoch, r_epoch))
        self._consensus_version = consensus_version
        self.commit()

    def _migrate_frames_data(
        self, current_frames: list[Frame], new_frames: list[Frame]
    ) -> tuple[StateData, dict[Frame, bool]]:
        migration_status = {frame: False for frame in current_frames}
        new_data: StateData = {frame: defaultdict(AttestationsAccumulator) for frame in new_frames}

        logger.info({"msg": f"Migrating duties data cache: {current_frames=} -> {new_frames=}"})

        for current_frame in current_frames:
            curr_frame_l_epoch, curr_frame_r_epoch = current_frame
            for new_frame in new_frames:
                if current_frame == new_frame:
                    new_data[new_frame] = self.data[current_frame]
                    migration_status[current_frame] = True
                    break

                new_frame_l_epoch, new_frame_r_epoch = new_frame
                if curr_frame_l_epoch >= new_frame_l_epoch and curr_frame_r_epoch <= new_frame_r_epoch:
                    logger.info({"msg": f"Migrating frame duties data cache: {current_frame=} -> {new_frame=}"})
                    for val, duty in self.data[current_frame].items():
                        new_data[new_frame][val].assigned += duty.assigned
                        new_data[new_frame][val].included += duty.included
                    migration_status[current_frame] = True
                    break

        return new_data, migration_status

    def validate(self, l_epoch: EpochNumber, r_epoch: EpochNumber) -> None:
        if not self.is_fulfilled:
            raise InvalidState(f"State is not fulfilled. {self.unprocessed_epochs=}")

        for epoch in self._processed_epochs:
            if not l_epoch <= epoch <= r_epoch:
                raise InvalidState(f"Processed epoch {epoch} is out of range")

        for epoch in sequence(l_epoch, r_epoch):
            if epoch not in self._processed_epochs:
                raise InvalidState(f"Epoch {epoch} missing in processed epochs")

    def get_network_aggr(self, frame: Frame) -> AttestationsAccumulator:
        # TODO: exclude `active_slashed` validators from the calculation
        included = assigned = 0
        frame_data = self.data.get(frame)
        if frame_data is None:
            raise ValueError(f"No data for frame {frame} to calculate network aggregate")
        for validator, acc in frame_data.items():
            if acc.included > acc.assigned:
                raise ValueError(f"Invalid accumulator: {validator=}, {acc=}")
            included += acc.included
            assigned += acc.assigned
        aggr = AttestationsAccumulator(
            included=included,
            assigned=assigned,
        )
        logger.info({"msg": "Network attestations aggregate computed", "value": repr(aggr), "avg_perf": aggr.perf})
        return aggr
