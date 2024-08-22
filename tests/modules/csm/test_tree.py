import pytest

from src.constants import UINT64_MAX
from src.modules.csm.tree import StandardMerkleTree, Tree, TreeJSONEncoder, TreeMeta
from src.providers.ipfs.cid import CIDv0
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


@pytest.fixture()
def meta() -> TreeMeta:
    return {"stateCID": CIDv0("Qm...")}


def test_non_null_root(tree: Tree):
    assert tree.root


def test_encode_decode(tree: Tree, meta: TreeMeta):
    decoded = Tree.decode(tree.encode(meta))
    assert decoded.root == tree.root

def test_metadata_in_dump(tree: Tree, meta: TreeMeta):
    dump = tree.dump(meta)
    assert "metadata" in dump
    assert dump["metadata"] == meta

def test_decode_plain_tree_dump(tree: Tree):
    decoded = Tree.decode(TreeJSONEncoder().encode(tree.tree.dump()).encode())
    assert decoded.root == tree.root


def test_dump_compatibility(tree: Tree, meta: TreeMeta):
    loaded = StandardMerkleTree.load(tree.dump(meta))
    assert loaded.root == tree.root
