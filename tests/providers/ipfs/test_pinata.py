import pytest
import requests
import responses

from src.providers.ipfs.pinata import Pinata
from src.providers.ipfs.cid import CID
from src.providers.ipfs.types import FetchError, UploadError, CIDValidationError


@pytest.mark.unit
class TestPinata:

    @pytest.fixture
    def pinata_provider(self):
        mock_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        return Pinata(jwt_token=mock_jwt, timeout=30)

    @responses.activate
    def test_fetch__valid_cid__returns_content(self, pinata_provider):
        cid = CID("QmXvrr3gPtddcNrisH7i2nan9rY7v7RcxVQ9jjRreoWwRS")
        expected_content = b"test content"

        responses.add(
            responses.GET,
            f"{Pinata.GATEWAY}/ipfs/QmXvrr3gPtddcNrisH7i2nan9rY7v7RcxVQ9jjRreoWwRS",
            body=expected_content,
            status=200,
        )

        result = pinata_provider.fetch(cid)

        assert result == expected_content
        assert len(responses.calls) == 1

    @responses.activate
    def test_fetch__request_fails__raises_fetch_error(self, pinata_provider):
        cid = CID("QmTestCid123")

        responses.add(
            responses.GET, f"{Pinata.GATEWAY}/ipfs/QmTestCid123", body=requests.ConnectionError("Network error")
        )

        with pytest.raises(FetchError):
            pinata_provider.fetch(cid)

    @responses.activate
    def test_fetch__http_error__raises_fetch_error(self, pinata_provider):
        cid = CID("QmTestCid123")

        responses.add(responses.GET, f"{Pinata.GATEWAY}/ipfs/QmTestCid123", status=404)

        with pytest.raises(FetchError):
            pinata_provider.fetch(cid)

    @responses.activate
    def test_upload__successful__returns_cid(self, pinata_provider):
        content = b"mock car content for upload test"
        expected_response = {"IpfsHash": "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"}

        responses.add(
            responses.POST, f"{Pinata.API_ENDPOINT}/pinning/pinFileToIPFS", json=expected_response, status=200
        )

        result = pinata_provider.upload(content)

        assert str(result) == "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"
        assert len(responses.calls) == 1

    @responses.activate
    def test_upload__request_fails__raises_upload_error(self, pinata_provider):
        content = b"mock car content for upload test"

        responses.add(
            responses.POST,
            f"{Pinata.API_ENDPOINT}/pinning/pinFileToIPFS",
            body=requests.ConnectionError("Network error"),
        )

        with pytest.raises(UploadError):
            pinata_provider.upload(content)

    @responses.activate
    def test_upload__http_error__raises_upload_error(self, pinata_provider):
        content = b"mock car content for upload test"

        responses.add(responses.POST, f"{Pinata.API_ENDPOINT}/pinning/pinFileToIPFS", status=500)

        with pytest.raises(UploadError):
            pinata_provider.upload(content)

    @responses.activate
    def test_upload__invalid_json__raises_upload_error(self, pinata_provider):
        content = b"mock car content for upload test"

        responses.add(responses.POST, f"{Pinata.API_ENDPOINT}/pinning/pinFileToIPFS", body="invalid json", status=200)

        with pytest.raises(UploadError):
            pinata_provider.upload(content)

    @responses.activate
    def test_upload__missing_hash_key__raises_upload_error(self, pinata_provider):
        content = b"mock car content for upload test"
        invalid_response = {"WrongKey": "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"}

        responses.add(responses.POST, f"{Pinata.API_ENDPOINT}/pinning/pinFileToIPFS", json=invalid_response, status=200)

        with pytest.raises(UploadError):
            pinata_provider.upload(content)

    @responses.activate
    def test_publish__successful__returns_cid(self, pinata_provider):
        content = b"mock car content for upload test"
        upload_response = {"IpfsHash": "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"}

        responses.add(responses.POST, f"{Pinata.API_ENDPOINT}/pinning/pinFileToIPFS", json=upload_response, status=200)

        result = pinata_provider.publish(content)

        assert str(result) == "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"
        assert len(responses.calls) == 1

    @responses.activate
    def test_fetch__cid_validation_fails__raises_validation_error(self, pinata_provider):
        cid = CID("QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc")
        wrong_content = b"test content"

        responses.add(
            responses.GET,
            f"{Pinata.GATEWAY}/ipfs/QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc",
            body=wrong_content,
            status=200,
        )

        with pytest.raises(CIDValidationError):
            pinata_provider.fetch(cid)

    @responses.activate
    def test_publish__cid_validation_fails__raises_validation_error(self, pinata_provider):
        content = b"test content"

        # Mock successful upload that returns valid CID but wrong for this content
        upload_response = {"IpfsHash": "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"}

        responses.add(responses.POST, f"{Pinata.API_ENDPOINT}/pinning/pinFileToIPFS", json=upload_response, status=200)

        with pytest.raises(CIDValidationError):
            pinata_provider.publish(content)
