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

logger = logging.getLogger(__name__)


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

    data: dict[ValidatorIndex, AttestationsAggregate] = field(default_factory=dict)
    processed_epochs: set[EpochNumber] = field(default_factory=set)

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
        self.processed_epochs.clear()

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
                "msg": f"Processed {len(self.processed_epochs)} epochs",
                "assigned": assigned,
                "included": included,
                "avg_perf": self.avg_perf,
            }
        )

    @property
    def avg_perf(self) -> float:
        """Returns average performance of all validators in the cache"""
        return mean((aggr.perf for aggr in self.values())) if self.values() else 0

    @property
    def buffer(self) -> Path:
        return self.file().with_suffix(".buf")

    def __bool__(self) -> bool:
        return True
