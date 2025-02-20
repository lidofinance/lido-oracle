import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Self, Sequence

from hexbytes import HexBytes
from oz_merkle_tree import Dump, StandardMerkleTree

from src.modules.csm.types import RewardTreeLeaf, StrikeTreeLeaf
from src.providers.ipfs.cid import CID


class TreeJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, bytes):
            return f"0x{o.hex()}"
        if isinstance(o, CID):
            return str(o)
        return super().default(o)


@dataclass
class Tree[LeafType: Iterable](ABC):
    """A wrapper around StandardMerkleTree to cover use cases of the CSM oracle"""

    tree: StandardMerkleTree[LeafType]

    @property
    def root(self) -> HexBytes:
        return HexBytes(self.tree.root)

    @classmethod
    def decode(cls, content: bytes) -> Self:
        """Restore a tree from a supported binary representation"""

        try:
            return cls(StandardMerkleTree.load(json.loads(content)))
        except json.JSONDecodeError as e:
            raise ValueError("Unsupported tree format") from e

    def encode(self) -> bytes:
        """Convert the underlying StandardMerkleTree to a binary representation"""

        return (
            TreeJSONEncoder(
                indent=None,
                separators=(',', ':'),
                sort_keys=True,
            )
            .encode(self.dump())
            .encode()
        )

    def dump(self) -> Dump[LeafType]:
        return self.tree.dump()

    @classmethod
    @abstractmethod
    def new(cls, values: Sequence[LeafType]) -> Self:
        raise NotImplementedError


class RewardTree(Tree[RewardTreeLeaf]):
    @classmethod
    def new(cls, values) -> Self:
        """Create new instance around the wrapped tree out of the given values"""
        return cls(StandardMerkleTree(values, ("uint256", "uint256")))


class StrikeTree(Tree[StrikeTreeLeaf]):
    @classmethod
    def new(cls, values) -> Self:
        """Create new instance around the wrapped tree out of the given values"""
        return cls(StandardMerkleTree(values, ("uint256", "uint256[]")))
