import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from json import JSONDecodeError, JSONDecoder, JSONEncoder
from typing import Any, Iterable, Self, Sequence

from hexbytes import HexBytes
from oz_merkle_tree import Dump, StandardMerkleTree

from src.modules.csm.types import RewardsTreeLeaf, StrikesTreeLeaf
from src.providers.ipfs.cid import CID
from src.utils.types import hex_str_to_bytes


class TreeJSONEncoder(JSONEncoder):
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

    encoder: type[JSONEncoder] = TreeJSONEncoder
    decoder: type[JSONDecoder] = JSONDecoder

    @property
    def root(self) -> HexBytes:
        return HexBytes(self.tree.root)

    @classmethod
    def decode(cls, content: bytes) -> Self:
        """Restore a tree from a supported binary representation"""

        try:
            return cls(StandardMerkleTree.load(json.loads(content, cls=cls.decoder)))
        except JSONDecodeError as e:
            raise ValueError("Unsupported tree format") from e

    def encode(self) -> bytes:
        """Convert the underlying StandardMerkleTree to a binary representation"""

        return (
            self.encoder(
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


class RewardsTree(Tree[RewardsTreeLeaf]):
    @classmethod
    def new(cls, values) -> Self:
        """Create new instance around the wrapped tree out of the given values"""
        return cls(StandardMerkleTree(values, ("uint256", "uint256")))


class StrikeTreeJSONDecoder(JSONDecoder):
    # NOTE: object_pairs_hook is set unconditionally upon object initialisation, so it's required to
    # override the __init__ method.
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs, object_pairs_hook=self.__object_pairs_hook)

    @staticmethod
    def __object_pairs_hook(items: list[tuple[str, Any]]):
        def try_convert_all_hex_str_to_bytes(obj: Any):
            if isinstance(obj, list):
                return [try_convert_all_hex_str_to_bytes(item) for item in obj]
            if isinstance(obj, str) and obj.startswith("0x"):
                return hex_str_to_bytes(obj)
            return obj

        return {key: try_convert_all_hex_str_to_bytes(value) for key, value in items}


class StrikesTree(Tree[StrikesTreeLeaf]):
    decoder = StrikeTreeJSONDecoder

    @classmethod
    def new(cls, values) -> Self:
        """Create new instance around the wrapped tree out of the given values"""
        return cls(StandardMerkleTree(values, ("uint256", "bytes", "uint256[]")))
