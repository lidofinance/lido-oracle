import logging
from dataclasses import dataclass
from typing import TypeAlias, Literal

from hexbytes import HexBytes

from src.providers.ipfs import CID
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
    rebate: int
    strikes_tree_root: HexBytes
    strikes_tree_cid: CID | Literal[""]

    def as_tuple(self):
        # Tuple with report in correct order
        return (
            self.consensusVersion,
            self.ref_slot,
            self.tree_root,
            str(self.tree_cid),
            str(self.log_cid),
            self.distributed,
            self.rebate,
            self.strikes_tree_root,
            str(self.strikes_tree_cid),
        )
