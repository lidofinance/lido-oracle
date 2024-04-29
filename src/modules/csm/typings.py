import logging
import os
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
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


@dataclass(slots=True, repr=False)
class FramePerformance:
    """Data structure to store required data for performance calculation within the given frame."""

    l_slot: SlotNumber
    r_slot: SlotNumber

    aggr_per_val: dict[ValidatorIndex, AttestationsAggregate] = field(default_factory=dict)

    processed_epochs: set[EpochNumber] = field(default_factory=set)
    processed_roots: set[BlockRoot] = field(default_factory=set)

    stuck_operators: set[NodeOperatorId] = field(default_factory=set)

    # XXX: Discussable fields (just to make it easier to debug failures).
    to_distribute: int = 0
    last_cid: str | None = None

    __schema__: str | None = None

    EXTENSION = ".pkl"

    def __post_init__(self) -> None:
        self.__schema__ = self.schema()

    @classmethod
    def schema(cls) -> str:
        # pylint: disable=no-member
        return str(cls.__slots__)  # type: ignore

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

        os.replace(self.buffer, self.file(self.l_slot, self.r_slot))

    @classmethod
    def try_read(cls, l_slot: SlotNumber, r_slot: SlotNumber) -> Self:
        """Used to restore the object from the persistent storage."""

        file = cls.file(l_slot, r_slot)
        obj: Self | None = None

        try:
            with file.open(mode="rb") as f:
                obj = pickle.load(f)
                assert obj

                logger.info({"msg": f"Read {repr(obj)} from {file.absolute()}"})

                # TODO: To think about a better way to check for schema changes.
                if cls.schema() != obj.__schema__:
                    raise ValueError("Schema mismatch")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.info({"msg": f"Unable to restore FramePerformance instance from {file.absolute()}", "error": str(e)})

        return obj or cls(l_slot=l_slot, r_slot=r_slot)

    @property
    def is_coherent(self) -> bool:
        return (self.r_slot - self.l_slot) // 32 == len(self.processed_epochs)

    @classmethod
    def file(cls, l_slot: SlotNumber, r_slot: SlotNumber) -> Path:
        return Path(f"{l_slot}_{r_slot}").with_suffix(cls.EXTENSION)

    @property
    def buffer(self) -> Path:
        return self.file(self.l_slot, self.r_slot).with_suffix(".buf")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(l_slot={self.l_slot},r_slot={self.r_slot})"
