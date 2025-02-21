import logging
from dataclasses import dataclass
from typing import Iterable, Literal, Sequence, TypeAlias

from hexbytes import HexBytes

from src.providers.ipfs import CID
from src.types import NodeOperatorId, SlotNumber

logger = logging.getLogger(__name__)


class StrikesList(Sequence[int]):
    """Deque-like structure to store strikes"""

    sentinel: int
    data: list[int]

    def __init__(self, data: Iterable[int]) -> None:
        self.data = list(data)
        self.sentinel = 0

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, index):
        return self.data[index]

    def __eq__(self, value: object, /) -> bool:
        return self.data.__eq__(value)

    def __repr__(self) -> str:
        return repr(self.data)

    def resize(self, maxlen: int) -> None:
        """Update maximum length of the list"""
        self.data = self.data[:maxlen] + [self.sentinel] * (maxlen - len(self.data))

    def push(self, item: int) -> None:
        """Push element at the beginning of the list discarding the last element"""
        self.data.insert(0, item)
        self.data.pop(-1)


Shares: TypeAlias = int
type RewardsTreeLeaf = tuple[NodeOperatorId, Shares]
type StrikesTreeLeaf = tuple[NodeOperatorId, bytes, StrikesList]


@dataclass
class ReportData:
    consensusVersion: int
    ref_slot: SlotNumber
    tree_root: HexBytes
    tree_cid: CID | Literal[""]
    log_cid: CID
    distributed: int

    def as_tuple(self):
        # Tuple with report in correct order
        return (
            self.consensusVersion,
            self.ref_slot,
            self.tree_root,
            str(self.tree_cid),
            str(self.log_cid),
            self.distributed,
        )
