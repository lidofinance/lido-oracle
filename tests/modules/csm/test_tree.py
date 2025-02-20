from abc import ABC, abstractmethod
from typing import Iterable, Self

import pytest
from eth_typing import HexStr
from web3.types import Timestamp
from src.utils.types import hex_str_to_bytes

from src.constants import UINT64_MAX
from src.modules.csm.tree import RewardTree, StandardMerkleTree, StrikeTree, Tree, TreeJSONEncoder
from src.modules.csm.types import RewardTreeLeaf, StrikeTreeLeaf
from src.types import NodeOperatorId


class TreeTestBase[LeafType: Iterable](ABC):
    type TreeType = Tree[LeafType]

    cls: type[Tree[LeafType]]

    @property
    @abstractmethod
    def values(self) -> list[LeafType]:
        raise NotImplementedError

    @pytest.fixture()
    def tree(self) -> TreeType:
        return self.cls.new(self.values)

    def test_non_null_root(self, tree: TreeType):
        assert tree.root

    def test_encode_decode(self, tree: TreeType):
        decoded = self.cls.decode(tree.encode())
        assert decoded.root == tree.root

        decoded_values = [v["value"] for v in decoded.tree.values]
        assert decoded_values == convert_tuples(self.values)

    def test_decode_plain_tree_dump(self, tree: TreeType):
        decoded = self.cls.decode(TreeJSONEncoder().encode(tree.tree.dump()).encode())
        assert decoded.root == tree.root

    def test_dump_compatibility(self, tree: TreeType):
        loaded = StandardMerkleTree.load(tree.dump())
        assert loaded.root == tree.root


type SimpleLeaf = tuple[int]


class SimpleTree(Tree[SimpleLeaf]):
    @classmethod
    def new(cls, values) -> Self:
        return cls(StandardMerkleTree(values, ("uint256",)))


class TestSimpleTree(TreeTestBase[SimpleLeaf]):
    cls = SimpleTree

    @property
    def values(self):
        return [
            (0,),
            (1,),
            (2,),
            (UINT64_MAX,),
        ]


class TestRewardTree(TreeTestBase[RewardTreeLeaf]):
    cls = RewardTree

    @property
    def values(self) -> list[RewardTreeLeaf]:
        return [
            (NodeOperatorId(0), 0),
            (NodeOperatorId(1), 1),
            (NodeOperatorId(2), 42),
            (NodeOperatorId(UINT64_MAX), 0),
        ]


class TestStrikeTree(TreeTestBase[StrikeTreeLeaf]):
    cls = StrikeTree

    @property
    def values(self) -> list[StrikeTreeLeaf]:
        return [
            (NodeOperatorId(0), hex_str_to_bytes("0x00"), [Timestamp(0)]),
            (NodeOperatorId(1), hex_str_to_bytes("0x01"), [Timestamp(1)]),
            (NodeOperatorId(1), hex_str_to_bytes("0x02"), [Timestamp(1)]),
            (NodeOperatorId(2), hex_str_to_bytes("0x03"), [Timestamp(42)]),
            (NodeOperatorId(UINT64_MAX), hex_str_to_bytes("0x64"), [Timestamp(1), Timestamp(2), Timestamp(3)]),
        ]


def convert_tuples(obj: Iterable):
    """
    A helper that converts all tuples in an iterable to lists. JSON has no notion of a tuple, so in
    order to compare values with those decoded from JSON, a conversion is required.
    """

    if isinstance(obj, tuple):
        return [convert_tuples(item) for item in obj]
    elif isinstance(obj, list):
        return [convert_tuples(item) for item in obj]
    else:
        return obj
