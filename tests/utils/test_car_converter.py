import pytest

from src.providers.ipfs.cid import is_cid_v0
from src.utils.car import CARConverter
from src.utils.car.converter import DEFAULT_CHUNK_SIZE


@pytest.mark.unit
class TestCARConverter:
    @pytest.fixture
    def converter(self):
        return CARConverter()

    def test_build_unixfs_blocks_and_root__single_chunk__returns_one_block(self, converter):
        data = b"test content"

        root_cid, blocks = converter._build_unixfs_blocks_and_root(data)

        assert len(blocks) == 1
        assert blocks[0][0] == root_cid
        assert is_cid_v0(root_cid.encode())

    def test_build_unixfs_blocks_and_root__multiple_chunks__returns_multiple_blocks_plus_parent(self, converter):
        data = b"x" * (DEFAULT_CHUNK_SIZE + 100)

        root_cid, blocks = converter._build_unixfs_blocks_and_root(data)

        assert len(blocks) == 3  # 2 leaf blocks + 1 parent block
        assert blocks[-1][0] == root_cid  # Last block is parent/root
        assert is_cid_v0(root_cid.encode())

    def test_build_unixfs_blocks_and_root__empty_data__returns_single_block(self, converter):
        data = b""

        root_cid, blocks = converter._build_unixfs_blocks_and_root(data)

        assert len(blocks) == 1
        assert blocks[0][0] == root_cid
        assert is_cid_v0(root_cid.encode())
