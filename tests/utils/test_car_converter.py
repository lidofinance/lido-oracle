import pytest

from src.utils.car import CARConverter
from src.utils.car.converter import DEFAULT_CHUNK_SIZE
from src.providers.ipfs.cid import is_cid_v0


@pytest.mark.unit
class TestCARConverter:

    @pytest.fixture
    def converter(self):
        return CARConverter()

    @pytest.fixture
    def test_data(self):
        return b"test content for CAR archive"

    def test_create_car_from_data__valid_data__returns_car_archive(self, converter, test_data):
        car_file = converter.create_car_from_data(test_data)

        assert len(car_file.car_bytes) > 0
        assert car_file.size == len(car_file.car_bytes)
        assert is_cid_v0(car_file.root_cid)

    def test_create_car_from_data__empty_data__returns_car_archive(self, converter):
        empty_data = b""

        car_file = converter.create_car_from_data(empty_data)

        assert len(car_file.car_bytes) > 0
        assert is_cid_v0(car_file.root_cid)
        assert car_file.size == len(car_file.car_bytes)

    def test_create_car_from_data__different_data__returns_different_cids(self, converter):
        data1 = b"first test content"
        data2 = b"second test content"

        car_file1 = converter.create_car_from_data(data1)
        car_file2 = converter.create_car_from_data(data2)

        assert car_file1.root_cid != car_file2.root_cid
        assert is_cid_v0(car_file1.root_cid)
        assert is_cid_v0(car_file2.root_cid)
        assert car_file1.shard_cid != car_file2.shard_cid
        assert car_file1.car_bytes != car_file2.car_bytes
        assert car_file1.size != car_file2.size

    def test_create_car_from_data__same_data__returns_same_cids(self, converter):
        data = b"identical test content"

        car_file1 = converter.create_car_from_data(data)
        car_file2 = converter.create_car_from_data(data)

        assert car_file1.root_cid == car_file2.root_cid
        assert is_cid_v0(car_file1.root_cid)
        assert is_cid_v0(car_file2.root_cid)
        assert car_file1.shard_cid == car_file2.shard_cid
        assert car_file1.size == car_file2.size
        assert car_file1.car_bytes == car_file2.car_bytes

    def test_create_car_from_data__exact_chunk_size__single_chunk_logic(self, converter):
        data = b"x" * DEFAULT_CHUNK_SIZE

        car_file = converter.create_car_from_data(data)

        assert len(car_file.car_bytes) > 0
        assert is_cid_v0(car_file.root_cid)
        assert car_file.size == len(car_file.car_bytes)

    def test_create_car_from_data__large_file__multiple_chunk_logic(self, converter):
        data = b"x" * (DEFAULT_CHUNK_SIZE * 3 + 50000)

        car_file = converter.create_car_from_data(data)

        assert len(car_file.car_bytes) > 0
        assert is_cid_v0(car_file.root_cid)
        assert car_file.size == len(car_file.car_bytes)

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
