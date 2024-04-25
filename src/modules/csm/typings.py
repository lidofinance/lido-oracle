import logging
import pickle
from dataclasses import dataclass, field
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


# INFO: Using slots here to compare after loading and object from pickle.
@dataclass(slots=True)
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

    def __post_init__(self) -> None:
        self.__schema__ = self.schema()

    @classmethod
    def schema(cls) -> str:
        return str(cls.__slots__)  # pylint: disable=no-member

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

        with open(self.filename(self.l_slot), mode="wb") as f:
            pickle.dump(self, f)

    @classmethod
    def try_read(cls, l_slot: SlotNumber) -> Self | None:
        """Used to restore the object from the persistent storage."""

        filename = cls.filename(l_slot)
        obj = None

        try:
            with open(filename, mode="rb") as f:
                obj = pickle.load(f)
                # TODO: To think about a better way to check for schema changes.
                if cls.schema() != obj.__schema__:
                    raise ValueError("Schema mismatch")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.info({"msg": f"Unable to restore FramePerformance instance from {filename}", "error": str(e)})

        return obj

    @property
    def is_coherent(self) -> bool:
        return (self.r_slot - self.l_slot) // 32 == len(self.processed_epochs)

    @staticmethod
    def filename(l_slot: SlotNumber) -> str:
        return f"{l_slot}.pkl"
