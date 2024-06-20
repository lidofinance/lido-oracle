import json
from dataclasses import dataclass
from typing import Self, Sequence, TypeAlias

from hexbytes import HexBytes
from oz_merkle_tree import StandardMerkleTree

from src.web3py.extensions.lido_validators import NodeOperatorId

Shares: TypeAlias = int
Leaf: TypeAlias = tuple[NodeOperatorId, Shares]


@dataclass
class Tree:
    """A wrapper around StandardMerkleTree to cover use cases of the CSM oracle"""

    tree: StandardMerkleTree[Leaf]

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

        def default(o):
            if isinstance(o, bytes):
                return f"0x{o.hex()}"
            raise ValueError(f"Unexpected type for json encoding, got {repr(o)}")

        return json.dumps(self.tree.dump(), indent=2, default=default).encode()

    @classmethod
    def new(cls, values: Sequence[Leaf]) -> Self:
        """Create new instance around the wrapped tree out of the given values"""
        return cls(StandardMerkleTree(values, ("uint256", "uint256")))
