from src.providers.ipfs import CIDv1
from src.modules.csm.types import CIDv1Serializable


class ObjectCIDv1(CIDv1Serializable):
    def __init__(self, data: bytes):
        self.data = data

    def encode(self) -> bytes:
        return self.data


def test_cid_generation():
    obj = ObjectCIDv1(b'IPFS 8 my bytes\n')

    assert obj.get_cid() == CIDv1('bafybeihtfzc5yv2ujbbbcw2jhvvmwom7hyqrwawnz4ojdzb357furea3pu')
