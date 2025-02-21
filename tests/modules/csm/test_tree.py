from abc import ABC, abstractmethod
from json import JSONDecoder, JSONEncoder
from typing import Iterable

import pytest

from src.constants import UINT64_MAX
from src.modules.csm.tree import RewardsTree, StandardMerkleTree, StrikesTree, Tree, TreeJSONEncoder
from src.modules.csm.types import RewardsTreeLeaf, StrikesList, StrikesTreeLeaf
from src.types import NodeOperatorId
from src.utils.types import hex_str_to_bytes


class TreeTestBase[LeafType: Iterable](ABC):
    type TreeType = Tree[LeafType]

    cls: type[Tree[LeafType]]

    @property
    def encoder(self) -> JSONEncoder:
        return self.cls.encoder()

    @property
    def decoder(self) -> JSONDecoder:
        return self.cls.decoder()

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

        json_encode = self.encoder.encode
        decoded_values = [v["value"] for v in decoded.tree.values]
        assert json_encode(decoded_values) == json_encode(self.values)

    def test_decode_plain_tree_dump(self, tree: TreeType):
        decoded = self.cls.decode(self.encoder.encode(tree.tree.dump()).encode())
        assert decoded.root == tree.root

    def test_dump_compatibility(self, tree: TreeType):
        loaded = StandardMerkleTree.load(tree.dump())
        assert loaded.root == tree.root


class TestRewardsTree(TreeTestBase[RewardsTreeLeaf]):
    cls = RewardsTree

    @property
    def values(self) -> list[RewardsTreeLeaf]:
        return [
            (NodeOperatorId(0), 0),
            (NodeOperatorId(1), 1),
            (NodeOperatorId(2), 42),
            (NodeOperatorId(UINT64_MAX), 0),
        ]


class TestStrikesTree(TreeTestBase[StrikesTreeLeaf]):
    cls = StrikesTree

    @property
    def values(self) -> list[StrikesTreeLeaf]:
        return [
            (NodeOperatorId(0), hex_str_to_bytes("0x00"), StrikesList([0])),
            (NodeOperatorId(1), hex_str_to_bytes("0x01"), StrikesList([1])),
            (NodeOperatorId(1), hex_str_to_bytes("0x02"), StrikesList([1])),
            (NodeOperatorId(2), hex_str_to_bytes("0x03"), StrikesList([1])),
            (NodeOperatorId(UINT64_MAX), hex_str_to_bytes("0x64"), StrikesList([1, 0, 1])),
        ]
