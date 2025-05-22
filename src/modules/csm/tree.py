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
            return HexBytes(o).to_0x_hex()
        return super().default(o)


class TreeJSONDecoder(JSONDecoder): ...


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

    @property
    def values(self) -> list[LeafType]:
        return [v["value"] for v in self.tree.values]

    @classmethod
    def decode(cls, content: bytes) -> Self:
        """Restore a tree from a supported binary representation"""

        try:
            return cls(StandardMerkleTree.load(json.loads(content, cls=cls.decoder)))
        except JSONDecodeError as e:
            raise ValueError("Invalid tree's JSON") from e
        except Exception as e:
            raise ValueError("Unable to load tree") from e

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


class RewardsTreeJSONDecoder(TreeJSONDecoder):
    # NOTE: object_pairs_hook is set unconditionally upon object initialisation, so it's required to
    # override the __init__ method.
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs, object_pairs_hook=self.__object_pairs_hook)

    @staticmethod
    def __object_pairs_hook(items: list[tuple[str, Any]]):
        def try_decode_value(key: str, obj: Any):
            if key != "value":
                return obj
            if not isinstance(obj, list) or not len(obj) == 2:
                raise ValueError(f"Unexpected RewardsTreeLeaf value given {obj=}")
            no_id, shares = obj
            if not isinstance(no_id, int):
                raise ValueError(f"Unexpected RewardsTreeLeaf value given {obj=}")
            if not isinstance(shares, int):
                raise ValueError(f"Unexpected RewardsTreeLeaf value given {obj=}")
            return no_id, shares

        return {k: try_decode_value(k, v) for k, v in items}


class RewardsTree(Tree[RewardsTreeLeaf]):
    decoder = RewardsTreeJSONDecoder

    @classmethod
    def new(cls, values) -> Self:
        """Create new instance around the wrapped tree out of the given values"""
        return cls(StandardMerkleTree(values, ("uint256", "uint256")))


class StrikesTreeJSONEncoder(TreeJSONEncoder):
    def default(self, o):
        if isinstance(o, StrikesList):
            return list(o)
        return super().default(o)


class StrikesTreeJSONDecoder(TreeJSONDecoder):
    # NOTE: object_pairs_hook is set unconditionally upon object initialisation, so it's required to
    # override the __init__ method.
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs, object_pairs_hook=self.__object_pairs_hook)

    @staticmethod
    def __object_pairs_hook(items: list[tuple[str, Any]]):
        def try_decode_value(key: str, obj: Any):
            if key != "value":
                return obj
            if not isinstance(obj, list) or not len(obj) == 3:
                raise ValueError(f"Unexpected StrikesTreeLeaf value given {obj=}")
            no_id, pubkey, strikes = obj
            if not isinstance(no_id, int):
                raise ValueError(f"Unexpected StrikesTreeLeaf value given {obj=}")
            if not isinstance(pubkey, str) or not pubkey.startswith("0x"):
                raise ValueError(f"Unexpected StrikesTreeLeaf value given {obj=}")
            if not isinstance(strikes, list):
                raise ValueError(f"Unexpected StrikesTreeLeaf value given {obj=}")
            return no_id, HexBytes(hex_str_to_bytes(pubkey)), StrikesList(strikes)

        return {k: try_decode_value(k, v) for k, v in items}


class StrikesTree(Tree[StrikesTreeLeaf]):
    encoder = StrikesTreeJSONEncoder
    decoder = StrikesTreeJSONDecoder

    @classmethod
    def new(cls, values) -> Self:
        """Create new instance around the wrapped tree out of the given values"""
        return cls(StandardMerkleTree(values, ("uint256", "bytes", "uint256[]")))
