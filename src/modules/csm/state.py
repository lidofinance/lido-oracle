from functools import reduce
import logging
import os
import pickle
from typing import Self
from collections import UserDict
from dataclasses import dataclass, field
from statistics import mean
from pathlib import Path

from src.typings import EpochNumber, ValidatorIndex
from src.utils.range import sequence

logger = logging.getLogger(__name__)


class InvalidState(Exception):
    ...


class InvalidStateLeftBorder(InvalidState):
    ...


class InvalidStateRightBorder(InvalidState):
    ...


@dataclass
class AttestationsAggregate:
    assigned: int
    included: int

    @property
    def perf(self) -> float:
        return self.included / self.assigned


@dataclass
class State(UserDict[ValidatorIndex, AttestationsAggregate]):
    """Tracks processing state of CSM performance oracle frame"""
    l_epoch: EpochNumber = field(default_factory=int)
    r_epoch: EpochNumber = field(default_factory=int)
    data: dict[ValidatorIndex, AttestationsAggregate] = field(default_factory=dict)
    epochs_to_process: set[EpochNumber] = field(default_factory=set)

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

    def is_empty(self) -> bool:
        return not self.data and not self.epochs_to_process and not self.l_epoch and not self.r_epoch

    def clear(self) -> None:
        self.l_epoch = EpochNumber(0)
        self.r_epoch = EpochNumber(0)
        self.data = {}
        self.epochs_to_process.clear()

    def inc(self, key: ValidatorIndex, included: bool) -> None:
        perf = self.get(key, AttestationsAggregate(0, 0))
        perf.assigned += 1
        perf.included += 1 if included else 0
        self[key] = perf

    def status(self) -> None:
        assigned, included = reduce(
            lambda acc, aggr: (acc[0] + aggr.assigned, acc[1] + aggr.included), self.values(), (0, 0)
        )

        logger.info(
            {
                "msg": f"Left {len(self.epochs_to_process)} epochs to process",
                "assigned": assigned,
                "included": included,
                "avg_perf": self.avg_perf,
            }
        )

    def validate(self, l_epoch: EpochNumber, r_epoch: EpochNumber) -> None:
        if self.l_epoch > 0 and self.l_epoch != l_epoch:
            logger.warning({"msg": f"Invalid left state border: should be {l_epoch=} but {self.l_epoch=}"})
            raise InvalidStateLeftBorder()

        if self.r_epoch > 0 and self.r_epoch != r_epoch:
            logger.warning({"msg": f"Invalid right state border: should be {r_epoch=} but {self.r_epoch=}"})
            raise InvalidStateRightBorder()

    def validate_and_adjust(self, l_epoch: EpochNumber, r_epoch: EpochNumber):

        def _discard():
            logger.warning({"msg": "Discarding invalidated state cache"})
            self.clear()
            self.commit()

        try:
            self.validate(l_epoch, r_epoch)
        except InvalidStateLeftBorder:
            _discard()
        except InvalidStateRightBorder:
            if self.r_epoch < r_epoch:
                _discard()
            else:
                logger.warning({"msg": "The last report was missed. Reuse the state with the new right border"})
                # expand the state to the new right border
                self.epochs_to_process.update(sequence(self.r_epoch - 1, r_epoch))
                self.r_epoch = r_epoch
                self.commit()

        if self.is_empty():
            logger.warning({"msg": "State cache is empty. Initialize the state"})
            self.l_epoch = l_epoch
            self.r_epoch = r_epoch
            self.epochs_to_process = set(sequence(l_epoch, r_epoch))
            self.commit()

    @property
    def avg_perf(self) -> float:
        """Returns average performance of all validators in the cache"""
        return mean((aggr.perf for aggr in self.values())) if self.values() else 0

    @property
    def buffer(self) -> Path:
        return self.file().with_suffix(".buf")

    def __bool__(self) -> bool:
        return True
