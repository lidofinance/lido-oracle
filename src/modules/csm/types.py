import logging
from abc import abstractmethod, ABC
from dataclasses import dataclass
from typing import TypeAlias, Literal

from hexbytes import HexBytes
from ipfs_cid import cid_sha256_hash  # type: ignore

from src.providers.ipfs import CID
from src.providers.ipfs import CIDv1
from src.types import NodeOperatorId, SlotNumber


logger = logging.getLogger(__name__)


Shares: TypeAlias = int
RewardTreeLeaf: TypeAlias = tuple[NodeOperatorId, Shares]


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


class CIDv1Serializable(ABC):
    @abstractmethod
    def encode(self) -> bytes:
        ...

    def get_cid(self) -> CIDv1:
        return CIDv1(cid_sha256_hash(self.encode()))
