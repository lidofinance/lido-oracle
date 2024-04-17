from dataclasses import dataclass, field
from hexbytes import HexBytes
from statistics import mean
from typing import Self

from src.typings import EpochNumber, SlotNumber, ValidatorIndex
from src.web3py.extensions.lido_validators import NodeOperatorId

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
        return self.assigned / self.included


@dataclass
class FramePerformance:
    """Data structure to store required data for performance calculation within the given frame."""

    l_slot: SlotNumber
    r_slot: SlotNumber

    aggr_per_val: dict[ValidatorIndex, AttestationsAggregate] = field(default_factory=dict)
    processed: set[EpochNumber] = field(default_factory=set)

    stuck_operators: set[NodeOperatorId] = field(default_factory=set)

    # XXX: Discussable fields (just to make it easier to debug failures).
    to_distribute: int = 0
    last_cid: str | None = None


    @property
    def avg_perf(self) -> float:
        """Returns average performance of all validators in the cache."""
        return mean((a.perf for a in self.aggr_per_val.values()))

    def dump(self) -> None:
        """Used to persist the current state of the structure."""

    @classmethod
    def try_read(cls, ref_slot: SlotNumber) -> Self | None:
        """Used to restore the object from the persistent storage."""

    @property
    def is_coherent(self) -> bool:
        return (self.r_slot - self.l_slot) // 32 == len(self.processed)
