import pytest

from src.constants import UINT64_MAX
from src.modules.csm.tree import StandardMerkleTree, Tree, TreeJSONEncoder
from src.types import NodeOperatorId


@pytest.fixture()
def tree():
    return Tree.new(
        [
            (NodeOperatorId(0), 0),
            (NodeOperatorId(1), 1),
            (NodeOperatorId(2), 42),
            (NodeOperatorId(UINT64_MAX), 0),
        ]
    )


@pytest.mark.unit
def test_non_null_root(tree: Tree):
    assert tree.root


@pytest.mark.unit
def test_encode_decode(tree: Tree):
    decoded = Tree.decode(tree.encode())
    assert decoded.root == tree.root


@pytest.mark.unit
def test_decode_plain_tree_dump(tree: Tree):
    decoded = Tree.decode(TreeJSONEncoder().encode(tree.tree.dump()).encode())
    assert decoded.root == tree.root


@pytest.mark.unit
def test_dump_compatibility(tree: Tree):
    loaded = StandardMerkleTree.load(tree.dump())
    assert loaded.root == tree.root
