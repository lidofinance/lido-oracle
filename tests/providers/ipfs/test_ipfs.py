import pytest
from multiformats.multibase.err import MultibaseKeyError

from src.providers.ipfs import IPFSProvider, CID, CIDv0


@pytest.mark.unit
def test_ipfs_upload():
    class TestIPFSProvider(IPFSProvider):
        def __init__(self, cid: str):
            self.cid = cid

        def _upload(self, *args):
            return self.cid

        def fetch(self, cid: CID) -> bytes: ...

        def pin(self, cid: CID) -> None: ...

    cid = TestIPFSProvider('QmPK1s3pNYLi9ERiq3BDxKa4XosgWwFRQUydHUtz4YgpqB').upload(b'hello world')

    assert isinstance(cid, CIDv0)
    assert cid == 'QmPK1s3pNYLi9ERiq3BDxKa4XosgWwFRQUydHUtz4YgpqB'

    cid = TestIPFSProvider('bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi').upload(b'hello world')
    assert isinstance(cid, CIDv0)
    assert cid == 'QmbWqxBEKC3P8tqsKc98xmWNzrzDtRLMiMPL8wBuTGsMnR'

    with pytest.raises(ValueError):
        # valid cid with json multicodec
        # Unsupported hash code 30
        TestIPFSProvider('bagaaihraf4oq2kddg6o5ewlu6aol6xab75xkwbgzx2dlot7cdun7iirve23a').upload(b'hello world')

    with pytest.raises(MultibaseKeyError):
        # multihash is not a valid base58 encoded multihash
        TestIPFSProvider('invalidcid').upload(b'hello world')
