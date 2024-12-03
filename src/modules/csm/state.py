import logging
import os
import pickle
from itertools import batched
from pathlib import Path
from typing import Self

from src.modules.csm.duties.attestation import (
    AttestationSequence,
    AttestationStatus,
    EpochIndexInFrame,
    calc_performance,
)
from src.types import EpochNumber, ValidatorIndex
from src.utils.range import sequence
from src.variables import CACHE_PATH

logger = logging.getLogger(__name__)


class InvalidState(ValueError):
    """State has data considered as invalid for a report"""


class State:
    """
    Processing state of a CSM performance oracle frame.

    During the CSM module startup the state object is being either `load`'ed from the filesystem or being created as a
    new object with no data in it. During epochs processing aggregates in `data` are being updated and eventually the
    state is `commit`'ed back to the filesystem.

    The state can be migrated to be used for another frame's report by calling the `migrate` method.
    """

    # validator_index -> AttestationSequence
    data: list[AttestationSequence]

    _epochs_to_process: tuple[EpochNumber, ...]
    _processed_epochs: set[EpochNumber]

    def __init__(self, data: list[AttestationSequence] | None = None) -> None:
        self.data = data or []
        self._epochs_to_process = tuple()
        self._processed_epochs = set()

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
        return CACHE_PATH / Path("cache").with_suffix(cls.EXTENSION)

    @property
    def buffer(self) -> Path:
        return self.file().with_suffix(".buf")

    def clear(self) -> None:
        self.data = []
        self._epochs_to_process = tuple()
        self._processed_epochs.clear()
        assert self.is_empty

    def get_epoch_index_in_frame(self, epoch: EpochNumber) -> EpochIndexInFrame:
        return EpochIndexInFrame(self._epochs_to_process.index(epoch))

    def set_duty_status(self, epoch: EpochNumber, val_index: ValidatorIndex, included: bool) -> None:
        if val_index >= len(self.data):
            self.data += [AttestationSequence(len(self._epochs_to_process))] * (val_index - len(self.data) + 1)
        self.data[val_index].set_duty_status(
            self.get_epoch_index_in_frame(epoch),
            AttestationStatus.INCLUDED if included else AttestationStatus.MISSED,
        )

    def get_duty_status(self, epoch: EpochNumber, val_index: ValidatorIndex) -> AttestationStatus:
        return self.data[val_index].get_duty_status(self.get_epoch_index_in_frame(epoch))

    def add_processed_epoch(self, epoch: EpochNumber) -> None:
        self._processed_epochs.add(epoch)

    def log_progress(self) -> None:
        logger.info({"msg": f"Processed {len(self._processed_epochs)} of {len(self._epochs_to_process)} epochs"})

    def migrate(self, l_epoch: EpochNumber, r_epoch: EpochNumber):
        new_epochs_to_process = tuple(sequence(l_epoch, r_epoch))
        if self._epochs_to_process == new_epochs_to_process:
            return

        # TODO: actually, we don't have to clear the cache in this case according to the current state logic
        #   if not, need to add `self._processed_epochs = self._processed_epochs.intersection(new_epochs_to_process)`
        for state_epochs in (self._epochs_to_process, self._processed_epochs):
            for epoch in state_epochs:
                if epoch < l_epoch or epoch > r_epoch:
                    logger.warning({"msg": "Discarding invalidated state cache"})
                    self.clear()
                    break

        if not self.is_empty:
            logger.info({"msg": "Migrating state data cache"})
            self._migrate_data(self._epochs_to_process, new_epochs_to_process)

        self._epochs_to_process = new_epochs_to_process
        self.commit()

    def _migrate_data(
        self, old_epochs_to_process: tuple[EpochNumber, ...], new_epochs_to_process: tuple[EpochNumber, ...]
    ):
        old_data = self.data
        self.data = [AttestationSequence(len(new_epochs_to_process)) for _ in range(len(old_data))]
        for i, old_attestations in enumerate(old_data):
            for j, old_epoch in enumerate(old_epochs_to_process):
                if old_epoch in new_epochs_to_process:
                    duty_status = old_attestations.get_duty_status(EpochIndexInFrame(j))
                    new_epoch_index = EpochIndexInFrame(new_epochs_to_process.index(old_epoch))
                    self.data[i].set_duty_status(new_epoch_index, duty_status)

    def validate(self, l_epoch: EpochNumber, r_epoch: EpochNumber) -> None:
        if not self.is_fulfilled:
            raise InvalidState(f"State is not fulfilled. {self.unprocessed_epochs=}")

        for epoch in self._processed_epochs:
            if not l_epoch <= epoch <= r_epoch:
                raise InvalidState(f"Processed epoch {epoch} is out of range")

        for epoch in sequence(l_epoch, r_epoch):
            if epoch not in self._processed_epochs:
                raise InvalidState(f"Epoch {epoch} should be processed")

    def calc_frames(self, epochs_per_frame: int) -> list[tuple[EpochNumber, EpochNumber]]:
        """Split epochs to process into frames of `epochs_per_frame` length"""
        frames = []
        for frame_epochs in batched(self._epochs_to_process, epochs_per_frame):
            if len(frame_epochs) < epochs_per_frame:
                raise ValueError("Epochs to process are not enough to form a frame")
            frames.append((frame_epochs[0], frame_epochs[-1]))
        return frames

    def calc_network_perf(self, from_epoch: EpochNumber, to_epoch: EpochNumber) -> float:
        # TODO: exclude `active_slashed` validators from the calculation
        from_epoch_index = self.get_epoch_index_in_frame(from_epoch)
        to_epoch_index = self.get_epoch_index_in_frame(to_epoch)

        all_missed = 0
        all_included = 0
        for validator_duties in self.data:
            all_missed += validator_duties.count_missed(from_epoch_index, to_epoch_index)
            all_included += validator_duties.count_included(from_epoch_index, to_epoch_index)
        network_perf = calc_performance(all_included, all_missed)

        logger.info(
            {
                "msg": "Network attestations aggregate computed",
                "missed": all_missed,
                "included": all_included,
                "perf": network_perf,
            }
        )
        return network_perf

    def count_missed(self, val_index: ValidatorIndex, from_epoch: EpochNumber, to_epoch: EpochNumber) -> int:
        from_epoch_index = self.get_epoch_index_in_frame(from_epoch)
        to_epoch_index = self.get_epoch_index_in_frame(to_epoch)
        return self.data[val_index].count_missed(from_epoch_index, to_epoch_index)

    def count_included(self, val_index: ValidatorIndex, from_epoch: EpochNumber, to_epoch: EpochNumber) -> int:
        from_epoch_index = self.get_epoch_index_in_frame(from_epoch)
        to_epoch_index = self.get_epoch_index_in_frame(to_epoch)
        return self.data[val_index].count_included(from_epoch_index, to_epoch_index)

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
