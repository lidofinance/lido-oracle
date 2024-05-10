import logging
from dataclasses import dataclass

from hexbytes import HexBytes

from src.providers.ipfs import CID
from src.typings import SlotNumber

logger = logging.getLogger(__name__)


@dataclass
class ReportData:
    consensusVersion: int
    ref_slot: SlotNumber
    tree_root: HexBytes
    tree_cid: CID
    distributed: int

    def as_tuple(self):
        # Tuple with report in correct order
        return (
            self.consensusVersion,
            self.ref_slot,
            self.tree_root,
            str(self.tree_cid),
            self.distributed,
        )
