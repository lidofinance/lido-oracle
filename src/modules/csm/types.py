import logging
from dataclasses import dataclass
from typing import TypeAlias, Literal

from hexbytes import HexBytes
from web3.types import Timestamp

from src.providers.ipfs import CID
from src.types import NodeOperatorId, SlotNumber

logger = logging.getLogger(__name__)


Shares: TypeAlias = int
type RewardTreeLeaf = tuple[NodeOperatorId, Shares]
type StrikeTreeLeaf = tuple[NodeOperatorId, list[Timestamp]]


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
