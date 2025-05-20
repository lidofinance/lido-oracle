import logging
from dataclasses import dataclass
from typing import Final, Iterable, Literal, Sequence, TypeAlias

from hexbytes import HexBytes

from src.providers.ipfs import CID
from src.types import NodeOperatorId, SlotNumber

logger = logging.getLogger(__name__)

type StrikesValidator = tuple[NodeOperatorId, HexBytes]


class StrikesList(Sequence[int]):
    """Deque-like structure to store strikes"""

    SENTINEL: Final = 0

    data: list[int]

    def __init__(self, data: Iterable[int] | None = None, maxlen: int | None = None) -> None:
        self.data = list(data or [])
        if maxlen:
            self.resize(maxlen)

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, index):
        return self.data[index]

    def __eq__(self, value: object, /) -> bool:
        if isinstance(value, StrikesList):
            return self.data == value.data
        return self.data == value

    def __repr__(self) -> str:
        return repr(self.data)

    def resize(self, maxlen: int) -> None:
        """Update maximum length of the list"""
        self.data = self.data[:maxlen] + [self.SENTINEL] * (maxlen - len(self.data))

    def push(self, item: int) -> None:
        """Push element at the beginning of the list resizing the list to keep one more item"""
        self.data.insert(0, item)


ParticipationShares: TypeAlias = int
RewardsShares: TypeAlias = int
type RewardsTreeLeaf = tuple[NodeOperatorId, RewardsShares]
type StrikesTreeLeaf = tuple[NodeOperatorId, HexBytes, StrikesList]


@dataclass
class ReportData:
    consensus_version: int
    ref_slot: SlotNumber
    tree_root: HexBytes
    tree_cid: CID | Literal[""]
    log_cid: CID
    distributed: int
    rebate: int
    strikes_tree_root: HexBytes
    strikes_tree_cid: CID | Literal[""]

    def as_tuple(self):
        # Tuple with report in correct order
        return (
            self.consensus_version,
            self.ref_slot,
            self.tree_root,
            str(self.tree_cid),
            str(self.log_cid),
            self.distributed,
            self.rebate,
            self.strikes_tree_root,
            str(self.strikes_tree_cid),
        )
