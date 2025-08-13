import pytest

from src.utils.car.converter import CARConverter
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
        car_bytes, root_cid, shard_cid, size = converter.create_car_from_data(test_data)

        assert len(car_bytes) > 0
        assert size == len(car_bytes)
        assert is_cid_v0(root_cid)

    def test_create_car_from_data__empty_data__returns_car_archive(self, converter):
        empty_data = b""

        car_bytes, root_cid, shard_cid, size = converter.create_car_from_data(empty_data)

        assert len(car_bytes) > 0
        assert is_cid_v0(root_cid)
        assert size == len(car_bytes)

    def test_create_car_from_data__large_data__returns_car_archive(self, converter):
        large_data = b"x" * 500000

        car_bytes, root_cid, shard_cid, size = converter.create_car_from_data(large_data)

        assert len(car_bytes) > len(large_data)
        assert is_cid_v0(root_cid)
        assert size == len(car_bytes)

    def test_create_car_from_data__different_data__returns_different_cids(self, converter):
        data1 = b"first test content"
        data2 = b"second test content"

        car_bytes1, root_cid1, shard_cid1, size1 = converter.create_car_from_data(data1)
        car_bytes2, root_cid2, shard_cid2, size2 = converter.create_car_from_data(data2)

        assert root_cid1 != root_cid2
        assert is_cid_v0(root_cid1)
        assert is_cid_v0(root_cid2)
        assert shard_cid1 != shard_cid2
        assert car_bytes1 != car_bytes2
        assert size1 != size2

    def test_create_car_from_data__same_data__returns_same_cids(self, converter):
        data = b"identical test content"

        car_bytes1, root_cid1, shard_cid1, size1 = converter.create_car_from_data(data)
        car_bytes2, root_cid2, shard_cid2, size2 = converter.create_car_from_data(data)

        assert root_cid1 == root_cid2
        assert is_cid_v0(root_cid1)
        assert is_cid_v0(root_cid2)
        assert shard_cid1 == shard_cid2
        assert size1 == size2
        assert car_bytes1 == car_bytes2
