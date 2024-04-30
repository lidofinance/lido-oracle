import logging
import os
import pickle
from dataclasses import dataclass, field, fields
from pathlib import Path
from statistics import mean
from threading import Timer
from typing import Any, Self

from hexbytes import HexBytes

from src.typings import BlockRoot, EpochNumber, SlotNumber, ValidatorIndex
from src.web3py.extensions.lido_validators import NodeOperatorId

logger = logging.getLogger(__name__)


@dataclass
class ReportData:
    consensusVersion: int
    ref_slot: SlotNumber
    tree_root: HexBytes
    tree_cid: str
    distributed: int

    def as_tuple(self):
        # Tuple with report in correct order
        return (
            self.consensusVersion,
            self.ref_slot,
            self.tree_root,
            self.tree_cid,
            self.distributed,
        )


@dataclass
class AttestationsAggregate:
    assigned: int
    included: int

    @property
    def perf(self) -> float:
        return self.included / self.assigned


SCHEMA_VERSION = 1


@dataclass(slots=True, repr=False)
class FramePerformance:
    """Data structure to store required data for performance calculation within the given frame."""

    l_slot: SlotNumber
    r_slot: SlotNumber

    aggr_per_val: dict[ValidatorIndex, AttestationsAggregate] = field(default_factory=dict)

    processed_epochs: set[EpochNumber] = field(default_factory=set)
    processed_roots: set[BlockRoot] = field(default_factory=set)

    stuck_operators: set[NodeOperatorId] = field(default_factory=set)

    version: int | None = None

    STATUS_INTERVAL = 300
    EXTENSION = ".pkl"

    def __post_init__(self) -> None:
        logger.info({"msg": f"New instance of {repr(self)} created"})
        self.version = self.version or SCHEMA_VERSION
        self.status()

    @property
    def avg_perf(self) -> float:
        """Returns average performance of all validators in the cache."""
        return mean((a.perf for a in self.aggr_per_val.values()))

    def dump(
        self,
        epoch: EpochNumber,
        committees: dict[Any, list[dict[str, str | bool]]],
        roots: set[BlockRoot],
    ) -> None:
        """Used to persist the current state of the structure."""
        # TODO: persist the data. no sense to keep it in memory (except of `processed` ?)
        self.processed_epochs.add(epoch)
        self.processed_roots.update(roots)
        for committee in committees.values():
            for validator in committee:
                key = ValidatorIndex(int(validator['index']))
                perf_data = self.aggr_per_val.get(key, AttestationsAggregate(0, 0))
                perf_data.assigned += 1
                perf_data.included += 1 if validator['included'] else 0
                self.aggr_per_val[key] = perf_data

        with self.buffer.open(mode="wb") as f:
            pickle.dump(self, f)

        os.replace(self.buffer, self.file())

    @classmethod
    def try_read(cls, l_slot: SlotNumber, r_slot: SlotNumber) -> Self:
        """Used to restore the object from the persistent storage."""

        file = cls.file()
        obj: Self | None = None

        try:
            with file.open(mode="rb") as f:
                obj = pickle.load(f)
                assert obj

                logger.info({"msg": f"{repr(obj)} read from {file.absolute()}"})
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.info({"msg": f"Unable to restore FramePerformance instance from {file.absolute()}", "error": str(e)})

        return obj or cls(l_slot=l_slot, r_slot=r_slot)

    @property
    def is_coherent(self) -> bool:
        return (self.r_slot - self.l_slot) // 32 == len(self.processed_epochs)

    @classmethod
    def file(cls) -> Path:
        return Path("cache").with_suffix(cls.EXTENSION)

    @property
    def buffer(self) -> Path:
        return self.file().with_suffix(".buf")

    def status(self) -> None:
        logger.info({"msg": f"Processed {len(self.processed_epochs)} epochs in the frame {self.l_slot}:{self.r_slot}"})
        Timer(self.STATUS_INTERVAL, self.status).start()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(l_slot={self.l_slot},r_slot={self.r_slot})"

    def __setstate__(self, state: dict) -> None:
        # @see https://github.com/python/cpython/blob/3.11/Lib/pickle.py#L1712-L1733
        if not isinstance(state, tuple) and len(state) == 2:
            raise ValueError("Unexpected 'state' structure")

        _, slotstate = state
        assert slotstate

        fields_ = tuple(f.name for f in fields(self))
        for k, v in slotstate.items():
            if k in fields_:
                setattr(self, k, v)

        # TODO: To think about a better way to check for schema changes.
        if not self.version or self.version != SCHEMA_VERSION:
            raise ValueError("Unexpected version")

        self.status()
