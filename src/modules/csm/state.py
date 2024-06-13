import logging
import os
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from src.types import EpochNumber, ValidatorIndex
from src.utils.range import sequence

logger = logging.getLogger(__name__)


class InvalidState(Exception): ...


@dataclass
class AttestationsAggregate:
    """Aggregate of attestations duties observed for a validator"""

    assigned: int
    included: int

    @property
    def perf(self) -> float:
        return self.included / self.assigned if self.assigned else 0


@dataclass
class State:
    """Processing state of a CSM performance oracle frame"""

    data: dict[ValidatorIndex, AttestationsAggregate] = field(default_factory=dict)

    _epochs_to_process: set[EpochNumber] = field(default_factory=set)
    _processed_epochs: set[EpochNumber] = field(default_factory=set)

    EXTENSION = ".pkl"

    @classmethod
    def load(cls) -> Self:
        """Used to restore the object from the persistent storage"""

        obj: Self | None = None
        file = cls.file()
        try:
            with file.open(mode="rb") as f:
                obj = pickle.load(f)
                assert obj

                logger.info({"msg": f"{cls.__name__} read from {file.absolute()}"})
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.info({"msg": f"Unable to restore {cls.__name__} instance from {file.absolute()}", "error": str(e)})
        return obj or cls()

    @classmethod
    def file(cls) -> Path:
        return Path("cache").with_suffix(cls.EXTENSION)

    def commit(self) -> None:
        with self.buffer.open(mode="wb") as f:
            pickle.dump(self, f)

        os.replace(self.buffer, self.file())

    def clear(self) -> None:
        self.data = {}
        self._epochs_to_process.clear()
        self._processed_epochs.clear()
        assert self.is_empty

    def inc(self, key: ValidatorIndex, included: bool) -> None:
        perf = self.data.get(key, AttestationsAggregate(0, 0))
        perf.assigned += 1
        perf.included += 1 if included else 0
        self.data[key] = perf

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

    def validate_for_report(self, l_epoch: EpochNumber, r_epoch: EpochNumber) -> None:
        if not self.is_fulfilled:
            raise InvalidState(f'State is not fulfilled. {self.unprocessed_epochs=}')

        for epoch in self._processed_epochs:
            if l_epoch <= epoch <= r_epoch:
                continue
            raise InvalidState(f'Processed epoch {epoch} is out of range')

        for epoch in sequence(l_epoch, r_epoch):
            if epoch not in self._processed_epochs:
                raise InvalidState(f'Epoch {epoch} should be processed')

    def validate_for_collect(self, l_epoch: EpochNumber, r_epoch: EpochNumber):
        invalidated = False

        for epoch in self._epochs_to_process:
            if l_epoch <= epoch <= r_epoch:
                continue
            invalidated = True
            break

        for epoch in self._processed_epochs:
            if l_epoch <= epoch <= r_epoch:
                continue
            invalidated = True
            break

        if invalidated:
            logger.warning({"msg": "Discarding invalidated state cache"})
            self.clear()
            self.commit()

        if self.is_empty or r_epoch > max(self._epochs_to_process):
            self._epochs_to_process.update(sequence(l_epoch, r_epoch))
            self.commit()

    @property
    def is_empty(self) -> bool:
        return not self.data and not self._epochs_to_process and not self._processed_epochs

    @property
    def unprocessed_epochs(self) -> set[EpochNumber]:
        if not self._epochs_to_process:
            raise ValueError("Epochs to process are not set")
        return self._epochs_to_process - self._processed_epochs

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
        for aggr in self.data.values():
            assert aggr.included <= aggr.assigned
            included += aggr.included
            assigned += aggr.assigned
        return AttestationsAggregate(
            included=included,
            assigned=assigned,
        )

    @property
    def buffer(self) -> Path:
        return self.file().with_suffix(".buf")

    def __bool__(self) -> bool:
        return True
