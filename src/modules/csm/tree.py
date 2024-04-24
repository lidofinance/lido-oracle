import json
from dataclasses import dataclass
from typing import Self, Sequence, TypeAlias

from oz_merkle_tree import StandardMerkleTree

from src.web3py.extensions.lido_validators import NodeOperatorId


Leaf: TypeAlias = tuple[NodeOperatorId, int]


@dataclass
class Tree:
    """A wrapper around StandardMerkleTree to cover use cases of the CSM oracle"""

    tree: StandardMerkleTree[Leaf]

    @property
    def root(self) -> str:
        return self.tree.root.hex()

    @classmethod
    def decode(cls, content: bytes) -> Self:
        """Restore a tree from a supported binary representation"""

        try:
            return cls(StandardMerkleTree.load(json.loads(content)))
        except json.JSONDecodeError as e:  # TODO: yaml is a way better, but no support out of the box.
            raise ValueError("Unsupported tree format") from e

    def encode(self) -> bytes:
        """Convert the underlying StandardMerkleTree to a binary representation"""
        return json.dumps(self.tree.dump(), indent=2).encode()

    @classmethod
    def new(cls, values: Sequence[Leaf]) -> Self:
        """Create new instance around the wrapped tree out of the given values"""
        return cls(StandardMerkleTree(values, ("uint256", "uint256")))
