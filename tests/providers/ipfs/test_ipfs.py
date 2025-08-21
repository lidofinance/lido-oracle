import pytest
from unittest.mock import patch
from multiformats.multibase.err import MultibaseKeyError

from src.providers.ipfs import IPFSProvider, CID, CIDv0
from src.providers.ipfs.types import CIDValidationError


@pytest.mark.unit
class TestIPFS:

    @pytest.fixture
    def test_provider(self):
        class TestIPFSProvider(IPFSProvider):
            def __init__(self, upload_cid: str = "QmPK1s3pNYLi9ERiq3BDxKa4XosgWwFRQUydHUtz4YgpqB"):
                super().__init__()
                self.upload_cid = upload_cid

            def _upload(self, content: bytes, name=None):
                return self.upload_cid

            def _fetch(self, cid: CID) -> bytes:
                return b'test content'

            def pin(self, cid: CID) -> None:
                pass

        return TestIPFSProvider

    def test_upload__v0_cid__returns_cidv0(self, test_provider):
        provider = test_provider('QmPK1s3pNYLi9ERiq3BDxKa4XosgWwFRQUydHUtz4YgpqB')
        cid = provider.upload(b'hello world')

        assert isinstance(cid, CIDv0)
        assert cid == 'QmPK1s3pNYLi9ERiq3BDxKa4XosgWwFRQUydHUtz4YgpqB'

    def test_upload__v1_cid__converts_to_v0(self, test_provider):
        provider = test_provider('bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi')
        cid = provider.upload(b'hello world')

        assert isinstance(cid, CIDv0)
        assert cid == 'QmbWqxBEKC3P8tqsKc98xmWNzrzDtRLMiMPL8wBuTGsMnR'

    def test_upload__json_multicodec__raises_value_error(self, test_provider):
        provider = test_provider('bagaaihraf4oq2kddg6o5ewlu6aol6xab75xkwbgzx2dlot7cdun7iirve23a')

        with pytest.raises(ValueError):
            # valid cid with json multicodec
            # Unsupported hash code 30
            provider.upload(b'hello world')

    def test_upload__invalid_cid__raises_multibase_key_error(self, test_provider):
        provider = test_provider('invalidcid')

        with pytest.raises(MultibaseKeyError):
            # multihash is not a valid base58 encoded multihash
            provider.upload(b'hello world')

    def test_fetch__cid_validation_fails__raises_validation_error(self, test_provider):
        provider = test_provider()
        # Use a valid CID format but with content that doesn't match
        cid = CID("QmPK1s3pNYLi9ERiq3BDxKa4XosgWwFRQUydHUtz4YgpqB")

        with pytest.raises(CIDValidationError):
            provider.fetch(cid)

    def test_publish__cid_validation_fails__raises_validation_error(self, test_provider):
        # Use a valid CID that doesn't match the content
        provider = test_provider("QmPK1s3pNYLi9ERiq3BDxKa4XosgWwFRQUydHUtz4YgpqB")
        content = b"mock car content for upload test"

        with pytest.raises(CIDValidationError):
            provider.publish(content)

    @patch('src.variables.IPFS_VALIDATE_CID', False)
    def test_fetch__validation_disabled__no_validation_performed(self, test_provider):
        provider = test_provider()
        cid = CID("QmPK1s3pNYLi9ERiq3BDxKa4XosgWwFRQUydHUtz4YgpqB")

        # Should not raise CIDValidationError when validation is disabled
        result = provider.fetch(cid)
        assert result == b'test content'

    @patch('src.variables.IPFS_VALIDATE_CID', False)
    def test_publish__validation_disabled__no_validation_performed(self, test_provider):
        provider = test_provider("QmPK1s3pNYLi9ERiq3BDxKa4XosgWwFRQUydHUtz4YgpqB")
        content = b"mock car content for upload test"

        # Should not raise CIDValidationError when validation is disabled
        result = provider.publish(content)
        assert isinstance(result, CIDv0)
