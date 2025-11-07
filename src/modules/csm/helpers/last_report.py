import logging
from dataclasses import dataclass
from functools import cached_property
from typing import Self, Iterable

from hexbytes import HexBytes

from src.modules.csm.tree import RewardsTree, StrikesTree
from src.modules.submodules.types import ZERO_HASH
from src.providers.execution.exceptions import InconsistentData
from src.providers.ipfs import CID
from src.types import BlockStamp, FrameNumber
from src.modules.csm.types import RewardsTreeLeaf, StrikesList, StrikesValidator
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


@dataclass
class LastReport:
    w3: Web3
    blockstamp: BlockStamp
    current_frame: FrameNumber

    rewards_tree_root: HexBytes
    strikes_tree_root: HexBytes
    rewards_tree_cid: CID | None
    strikes_tree_cid: CID | None

    @classmethod
    def load(cls, w3: Web3, blockstamp: BlockStamp, current_frame: FrameNumber) -> Self:
        rewards_tree_root = w3.csm.get_rewards_tree_root(blockstamp)
        rewards_tree_cid = w3.csm.get_rewards_tree_cid(blockstamp)

        if (rewards_tree_cid is None) != (rewards_tree_root == ZERO_HASH):
            raise InconsistentData(f"Got inconsistent previous tree data: {rewards_tree_root=} {rewards_tree_cid=}")

        strikes_tree_root = w3.csm.get_strikes_tree_root(blockstamp)
        strikes_tree_cid = w3.csm.get_strikes_tree_cid(blockstamp)

        if (strikes_tree_cid is None) != (strikes_tree_root == ZERO_HASH):
            raise InconsistentData(f"Got inconsistent previous tree data: {strikes_tree_root=} {strikes_tree_cid=}")

        return cls(
            w3,
            blockstamp,
            current_frame,
            rewards_tree_root,
            strikes_tree_root,
            rewards_tree_cid,
            strikes_tree_cid,
        )

    @cached_property
    def rewards(self) -> Iterable[RewardsTreeLeaf]:
        if self.rewards_tree_cid is None or self.rewards_tree_root == ZERO_HASH:
            logger.info({"msg": f"No rewards distribution as of {self.blockstamp=}."})
            return []

        logger.info({"msg": "Fetching rewards tree by CID from IPFS", "cid": repr(self.rewards_tree_cid)})
        tree = RewardsTree.decode(self.w3.ipfs.fetch(self.rewards_tree_cid, self.current_frame))

        logger.info({"msg": "Restored rewards tree from IPFS dump", "root": repr(tree.root)})

        if tree.root != self.rewards_tree_root:
            raise ValueError("Unexpected rewards tree root got from IPFS dump")

        return tree.values

    @cached_property
    def strikes(self) -> dict[StrikesValidator, StrikesList]:
        if self.strikes_tree_cid is None or self.strikes_tree_root == ZERO_HASH:
            logger.info({"msg": f"No strikes reported as of {self.blockstamp=}."})
            return {}

        logger.info({"msg": "Fetching strikes tree by CID from IPFS", "cid": repr(self.strikes_tree_cid)})
        tree = StrikesTree.decode(self.w3.ipfs.fetch(self.strikes_tree_cid, self.current_frame))

        logger.info({"msg": "Restored strikes tree from IPFS dump", "root": repr(tree.root)})

        if tree.root != self.strikes_tree_root:
            raise ValueError("Unexpected strikes tree root got from IPFS dump")

        return {(no_id, pubkey): strikes for no_id, pubkey, strikes in tree.values}
