from typing import Self

import pytest

from src.constants import UINT64_MAX
from src.modules.csm.tree import StandardMerkleTree, Tree, TreeJSONEncoder
from src.types import NodeOperatorId


class SimpleTree(Tree[tuple[NodeOperatorId, int]]):
    @classmethod
    def new(cls, values) -> Self:
        return cls(StandardMerkleTree(values, ("uint256", "uint256")))


@pytest.fixture()
def tree():
    return SimpleTree.new(
        [
            (NodeOperatorId(0), 0),
            (NodeOperatorId(1), 1),
            (NodeOperatorId(2), 42),
            (NodeOperatorId(UINT64_MAX), 0),
        ]
    )


def test_non_null_root(tree: SimpleTree):
    assert tree.root


def test_encode_decode(tree: SimpleTree):
    decoded = SimpleTree.decode(tree.encode())
    assert decoded.root == tree.root


def test_decode_plain_tree_dump(tree: SimpleTree):
    decoded = SimpleTree.decode(TreeJSONEncoder().encode(tree.tree.dump()).encode())
    assert decoded.root == tree.root


def test_dump_compatibility(tree: SimpleTree):
    loaded = StandardMerkleTree.load(tree.dump())
    assert loaded.root == tree.root
