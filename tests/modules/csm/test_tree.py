from abc import ABC, abstractmethod
from json import JSONDecoder, JSONEncoder
from typing import Iterable

import pytest
from hexbytes import HexBytes

from src.constants import UINT64_MAX
from src.modules.csm.tree import RewardsTree, StandardMerkleTree, StrikesTree, Tree
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

    @pytest.mark.unit
    def test_non_null_root(self, tree: TreeType):
        assert tree.root

    @pytest.mark.unit
    def test_encode_decode(self, tree: TreeType):
        decoded = self.cls.decode(tree.encode())
        assert decoded.values == self.values
        assert decoded.root == tree.root

    @pytest.mark.unit
    def test_decode_plain_tree_dump(self, tree: TreeType):
        decoded = self.cls.decode(self.encoder.encode(tree.tree.dump()).encode())
        assert decoded.root == tree.root

    @pytest.mark.unit
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
            (NodeOperatorId(0), HexBytes(hex_str_to_bytes("0x00")), StrikesList([0])),
            (NodeOperatorId(1), HexBytes(hex_str_to_bytes("0x01")), StrikesList([1])),
            (NodeOperatorId(1), HexBytes(hex_str_to_bytes("0x02")), StrikesList([1])),
            (NodeOperatorId(2), HexBytes(hex_str_to_bytes("0x03")), StrikesList([1])),
            (NodeOperatorId(UINT64_MAX), HexBytes(hex_str_to_bytes("0x64")), StrikesList([1, 0, 1])),
        ]

    @pytest.mark.unit
    def test_decoded_types(self, tree: StrikesTree) -> None:
        decoded = self.cls.decode(tree.encode())
        no_id, pk, strikes = decoded.values[0]
        assert isinstance(no_id, int)
        assert isinstance(pk, HexBytes)
        assert isinstance(strikes, StrikesList)
