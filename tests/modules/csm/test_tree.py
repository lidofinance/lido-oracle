import pytest
from eth_abi.exceptions import ValueOutOfBounds

from src.modules.csm.tree import Tree

# pyright: reportArgumentType=false


@pytest.fixture
def tree() -> Tree:
    return Tree.new(
        (
            (1, 1_000_000),
            (2, 999_999),
            (2**64, 0),
        )
    )


def test_tree_format(tree: Tree):
    assert tree.tree.encoding == ("uint256", "uint256")


def test_tree_throws_on_uint256_out_of_bounds():
    with pytest.raises(ValueOutOfBounds):
        Tree.new([(1, 2**256)])
    with pytest.raises(ValueOutOfBounds):
        Tree.new([(2**256, 1)])
    with pytest.raises(ValueOutOfBounds):
        Tree.new([(1, -1)])
    with pytest.raises(ValueOutOfBounds):
        Tree.new([(-1, 0)])


def test_tree_encode_decode(tree: Tree):
    assert Tree.decode(tree.encode()).root == tree.root, "Encoded->decoded tree's root doesn't match the original tree"
