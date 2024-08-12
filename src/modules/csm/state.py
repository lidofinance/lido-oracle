import logging
import os
import pickle
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from src.types import EpochNumber, ValidatorIndex
from src.utils.range import sequence

logger = logging.getLogger(__name__)


class InvalidState(ValueError):
    """State has data considered as invalid for a report"""


@dataclass
class AttestationsAggregate:
    """Aggregate of attestations duties observed for a validator"""

    assigned: int = 0
    included: int = 0

    @property
    def perf(self) -> float:
        return self.included / self.assigned if self.assigned else 0

    def inc(self, included: bool) -> None:
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

    data: defaultdict[ValidatorIndex, AttestationsAggregate]

    _epochs_to_process: tuple[EpochNumber, ...]
    _processed_epochs: set[EpochNumber]

    def __init__(self, data: dict[ValidatorIndex, AttestationsAggregate] | None = None) -> None:
        self.data = defaultdict(AttestationsAggregate, data or {})
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
        return Path("cache").with_suffix(cls.EXTENSION)

    @property
    def buffer(self) -> Path:
        return self.file().with_suffix(".buf")

    def clear(self) -> None:
        self.data = defaultdict(AttestationsAggregate)
        self._epochs_to_process = tuple()
        self._processed_epochs.clear()
        assert self.is_empty

    def inc(self, key: ValidatorIndex, included: bool) -> None:
        self.data[key].inc(included)

    def add_processed_epoch(self, epoch: EpochNumber) -> None:
        self._processed_epochs.add(epoch)

    def status(self) -> None:
        network_aggr = self.network_aggr

        logger.info(
            {
                "msg": f"Processed {len(self._processed_epochs)} of {len(self._epochs_to_process)} epochs",
                "assigned": network_aggr.assigned,
                "included": network_aggr.included,
                "avg_perf": self.avg_perf,
            }
        )

    def migrate(self, l_epoch: EpochNumber, r_epoch: EpochNumber):
        for state_epochs in (self._epochs_to_process, self._processed_epochs):
            for epoch in state_epochs:
                if epoch < l_epoch or epoch > r_epoch:
                    logger.warning({"msg": "Discarding invalidated state cache"})
                    self.clear()
                    break

        self._epochs_to_process = tuple(sequence(l_epoch, r_epoch))
        self.commit()

    def validate(self, l_epoch: EpochNumber, r_epoch: EpochNumber) -> None:
        if not self.is_fulfilled:
            raise InvalidState(f"State is not fulfilled. {self.unprocessed_epochs=}")

        for epoch in self._processed_epochs:
            if not l_epoch <= epoch <= r_epoch:
                raise InvalidState(f"Processed epoch {epoch} is out of range")

        for epoch in sequence(l_epoch, r_epoch):
            if epoch not in self._processed_epochs:
                raise InvalidState(f"Epoch {epoch} should be processed")

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
    def avg_perf(self) -> float:
        """Returns average performance of all validators in the cache"""
        return self.network_aggr.perf

    @property
    def network_aggr(self) -> AttestationsAggregate:
        included = assigned = 0
        for validator, aggr in self.data.items():
            if aggr.included > aggr.assigned:
                raise ValueError(f"Invalid aggregate: {validator=}, {aggr=}")
            included += aggr.included
            assigned += aggr.assigned
        return AttestationsAggregate(
            included=included,
            assigned=assigned,
        )
