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

type Frame = tuple[EpochNumber, EpochNumber]


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


class State:
    """
    Processing state of a CSM performance oracle frame.

    During the CSM module startup the state object is being either `load`'ed from the filesystem or being created as a
    new object with no data in it. During epochs processing aggregates in `data` are being updated and eventually the
    state is `commit`'ed back to the filesystem.

    The state can be migrated to be used for another frame's report by calling the `migrate` method.
    """
    att_data: dict[Frame, defaultdict[ValidatorIndex, DutyAccumulator]]
    prop_data: dict[Frame, defaultdict[ValidatorIndex, DutyAccumulator]]
    sync_data: dict[Frame, defaultdict[ValidatorIndex, DutyAccumulator]]

    _epochs_to_process: tuple[EpochNumber, ...]
    _processed_epochs: set[EpochNumber]
    _epochs_per_frame: int

    _consensus_version: int = 1

    def __init__(self, att_data: dict[Frame, dict[ValidatorIndex, DutyAccumulator]] | None = None) -> None:
        self.att_data = {
            frame: defaultdict(DutyAccumulator, validators) for frame, validators in (att_data or {}).items()
        }
        self.prop_data = {}
        self.sync_data = {}
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
        return (
            not self.att_data and
            not self.sync_data and
            not self.prop_data and
            not self._epochs_to_process and
            not self._processed_epochs
        )

    @property
    def unprocessed_epochs(self) -> set[EpochNumber]:
        if not self._epochs_to_process:
            raise ValueError("Epochs to process are not set")
        diff = set(self._epochs_to_process) - self._processed_epochs
        return diff

    @property
    def is_fulfilled(self) -> bool:
        return not self.unprocessed_epochs

    def clear(self) -> None:
        self.att_data = {}
        self.sync_data = {}
        self.prop_data = {}
        self._epochs_to_process = tuple()
        self._processed_epochs.clear()
        assert self.is_empty

    def find_frame(self, epoch: EpochNumber) -> Frame:
        frames = self.calculate_frames(self._epochs_to_process, self._epochs_per_frame)
        for epoch_range in frames:
            if epoch_range[0] <= epoch <= epoch_range[1]:
                return epoch_range
        raise ValueError(f"Epoch {epoch} is out of frames range: {frames}")

    def increment_att_duty(self, frame: Frame, val_index: ValidatorIndex, included: bool) -> None:
        self.att_data[frame][val_index].add_duty(included)

    def increment_prop_duty(self, frame: Frame, val_index: ValidatorIndex, included: bool) -> None:
        self.prop_data[frame][val_index].add_duty(included)

    def increment_sync_duty(self, frame: Frame, val_index: ValidatorIndex, included: bool) -> None:
        self.sync_data[frame][val_index].add_duty(included)

    def add_processed_epoch(self, epoch: EpochNumber) -> None:
        self._processed_epochs.add(epoch)

    def log_progress(self) -> None:
        logger.info({"msg": f"Processed {len(self._processed_epochs)} of {len(self._epochs_to_process)} epochs"})

    def init_or_migrate(
        self,
        l_epoch: EpochNumber,
        r_epoch: EpochNumber,
        epochs_per_frame: int,
        consensus_version: int
    ) -> None:
        if consensus_version != self._consensus_version:
            logger.warning(
                {
                    "msg": f"Cache was built for consensus version {self._consensus_version}. "
                    f"Discarding data to migrate to consensus version {consensus_version}"
                }
            )
            self.clear()

        if not self.is_empty:
            invalidated = self._migrate_or_invalidate(l_epoch, r_epoch, epochs_per_frame)
            if invalidated:
                self.clear()

        self._fill_frames(l_epoch, r_epoch, epochs_per_frame)
        self._epochs_per_frame = epochs_per_frame
        self._epochs_to_process = tuple(sequence(l_epoch, r_epoch))
        self._consensus_version = consensus_version
        self.commit()

    def _fill_frames(self, l_epoch: EpochNumber, r_epoch: EpochNumber, epochs_per_frame: int) -> None:
        frames = self.calculate_frames(tuple(sequence(l_epoch, r_epoch)), epochs_per_frame)
        for frame in frames:
            self.att_data.setdefault(frame, defaultdict(DutyAccumulator))
            self.prop_data.setdefault(frame, defaultdict(DutyAccumulator))
            self.sync_data.setdefault(frame, defaultdict(DutyAccumulator))

    def _migrate_or_invalidate(self, l_epoch: EpochNumber, r_epoch: EpochNumber, epochs_per_frame: int) -> bool:
        current_frames = self.calculate_frames(self._epochs_to_process, self._epochs_per_frame)
        new_frames = self.calculate_frames(tuple(sequence(l_epoch, r_epoch)), epochs_per_frame)
        inv_msg = f"Discarding invalid state cache because of frames change. {current_frames=}, {new_frames=}"

        if self._invalidate_on_epoch_range_change(l_epoch, r_epoch):
            logger.warning({"msg": inv_msg})
            return True

        frame_expanded = epochs_per_frame > self._epochs_per_frame
        frame_shrunk = epochs_per_frame < self._epochs_per_frame

        has_single_frame = len(current_frames) == len(new_frames) == 1

        if has_single_frame and frame_expanded:
            current_frame, *_ = current_frames
            new_frame, *_ = new_frames
            self.att_data[new_frame] = self.att_data.pop(current_frame)
            self.prop_data[new_frame] = self.prop_data.pop(current_frame)
            self.sync_data[new_frame] = self.sync_data.pop(current_frame)
            logger.info({"msg": f"Migrated state cache to a new frame. {current_frame=}, {new_frame=}"})
            return False

        if has_single_frame and frame_shrunk:
            logger.warning({"msg": inv_msg})
            return True

        if not has_single_frame and frame_expanded or frame_shrunk:
            logger.warning({"msg": inv_msg})
            return True

        return False

    def _invalidate_on_epoch_range_change(self, l_epoch: EpochNumber, r_epoch: EpochNumber) -> bool:
        """Check if the epoch range has been invalidated."""
        for epoch_set in (self._epochs_to_process, self._processed_epochs):
            if any(epoch < l_epoch or epoch > r_epoch for epoch in epoch_set):
                return True
        return False

    def validate(self, l_epoch: EpochNumber, r_epoch: EpochNumber) -> None:
        if not self.is_fulfilled:
            raise InvalidState(f"State is not fulfilled. {self.unprocessed_epochs=}")

        for epoch in self._processed_epochs:
            if not l_epoch <= epoch <= r_epoch:
                raise InvalidState(f"Processed epoch {epoch} is out of range")

        for epoch in sequence(l_epoch, r_epoch):
            if epoch not in self._processed_epochs:
                raise InvalidState(f"Epoch {epoch} missing in processed epochs")

    @staticmethod
    def calculate_frames(epochs_to_process: tuple[EpochNumber, ...], epochs_per_frame: int) -> list[Frame]:
        """Split epochs to process into frames of `epochs_per_frame` length"""
        frames = []
        for frame_epochs in batched(epochs_to_process, epochs_per_frame):
            if len(frame_epochs) < epochs_per_frame:
                raise ValueError("Insufficient epochs to form a frame")
            frames.append((frame_epochs[0], frame_epochs[-1]))
        return frames

    def get_att_network_aggr(self, frame: Frame) -> DutyAccumulator:
        # TODO: exclude `active_slashed` validators from the calculation
        included = assigned = 0
        frame_data = self.att_data.get(frame)
        if not frame_data:
            raise ValueError(f"No data for frame {frame} to calculate attestations network aggregate")
        for validator, acc in frame_data.items():
            if acc.included > acc.assigned:
                raise ValueError(f"Invalid accumulator: {validator=}, {acc=}")
            included += acc.included
            assigned += acc.assigned
        aggr = DutyAccumulator(
            included=included,
            assigned=assigned,
        )
        logger.info({"msg": "Network attestations aggregate computed", "value": repr(aggr), "avg_perf": aggr.perf})
        return aggr

    def get_sync_network_aggr(self, frame: Frame) -> DutyAccumulator:
        included = assigned = 0
        frame_data = self.sync_data.get(frame)
        if not frame_data:
            raise ValueError(f"No data for frame {frame} to calculate syncs network aggregate")
        for validator, acc in frame_data.items():
            if acc.included > acc.assigned:
                raise ValueError(f"Invalid accumulator: {validator=}, {acc=}")
            included += acc.included
            assigned += acc.assigned
        aggr = DutyAccumulator(
            included=included,
            assigned=assigned,
        )
        logger.info({"msg": "Network syncs aggregate computed", "value": repr(aggr), "avg_perf": aggr.perf})
        return aggr

    def get_prop_network_aggr(self, frame: Frame) -> DutyAccumulator:
        included = assigned = 0
        frame_data = self.prop_data.get(frame)
        if not frame_data:
            raise ValueError(f"No data for frame {frame} to calculate proposal network aggregate")
        for validator, acc in frame_data.items():
            if acc.included > acc.assigned:
                raise ValueError(f"Invalid accumulator: {validator=}, {acc=}")
            included += acc.included
            assigned += acc.assigned
        aggr = DutyAccumulator(
            included=included,
            assigned=assigned,
        )
        logger.info({"msg": "Network proposal aggregate computed", "value": repr(aggr), "avg_perf": aggr.perf})
        return aggr
