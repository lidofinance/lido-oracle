import json
from abc import ABC, abstractmethod
from json import JSONDecodeError, JSONDecoder, JSONEncoder
from typing import Any, ClassVar, Iterable, Self, Sequence

from hexbytes import HexBytes
from oz_merkle_tree import Dump, StandardMerkleTree

from src.modules.csm.types import RewardsTreeLeaf, StrikesList, StrikesTreeLeaf
from src.utils.types import hex_str_to_bytes


class TreeJSONEncoder(JSONEncoder):
    def default(self, o):
        if isinstance(o, bytes):
            return f"0x{o.hex()}"
        return super().default(o)


class TreeJSONDecoder(JSONDecoder):
    # NOTE: object_pairs_hook is set unconditionally upon object initialisation, so it's required to
    # override the __init__ method.
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs, object_pairs_hook=self.__object_pairs_hook)

    @staticmethod
    def __object_pairs_hook(items: list[tuple[str, Any]]):
        def try_convert_all_hex_str_to_bytes(obj: Any):
            if isinstance(obj, dict):
                return {k: try_convert_all_hex_str_to_bytes(v) for (k, v) in obj.items()}
            if isinstance(obj, list):
                return [try_convert_all_hex_str_to_bytes(item) for item in obj]
            if isinstance(obj, str) and obj.startswith("0x"):
                return hex_str_to_bytes(obj)
            return obj

        return {k: try_convert_all_hex_str_to_bytes(v) for k, v in items}


class Tree[LeafType: Iterable](ABC):
    """A wrapper around StandardMerkleTree to cover use cases of the CSM oracle"""

    encoder: ClassVar[type[JSONEncoder]] = TreeJSONEncoder
    decoder: ClassVar[type[JSONDecoder]] = TreeJSONDecoder

    tree: StandardMerkleTree[LeafType]

    def __init__(self, tree: StandardMerkleTree[LeafType]) -> None:
        self.tree = tree

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


class StrikesTreeJSONEncoder(TreeJSONEncoder):
    def default(self, o):
        if isinstance(o, StrikesList):
            return list(o)
        return super().default(o)


class StrikesTree(Tree[StrikesTreeLeaf]):
    encoder = StrikesTreeJSONEncoder

    @classmethod
    def new(cls, values) -> Self:
        """Create new instance around the wrapped tree out of the given values"""
        return cls(StandardMerkleTree(values, ("uint256", "bytes", "uint256[]")))
