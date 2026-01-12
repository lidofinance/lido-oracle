import pytest
import requests
import responses

from src.providers.ipfs.lido_ipfs import LidoIPFS
from src.providers.ipfs.cid import CID
from src.providers.ipfs.types import FetchError, UploadError, CIDValidationError


@pytest.mark.unit
class TestLidoIPFS:

    @pytest.fixture
    def lido_ipfs_provider(self):
        return LidoIPFS(host="https://ipfs-test.lido.fi", token="test_bearer_token", timeout=30)

    @responses.activate
    def test_fetch__valid_cid__returns_content(self, lido_ipfs_provider):
        cid = CID("QmXvrr3gPtddcNrisH7i2nan9rY7v7RcxVQ9jjRreoWwRS")
        expected_content = b"test content"

        responses.add(
            responses.GET,
            f"https://ipfs-test.lido.fi/ipfs/{cid}",
            body=expected_content,
            status=200,
        )

        result = lido_ipfs_provider.fetch(cid)

        assert result == expected_content
        assert len(responses.calls) == 1
        assert responses.calls[0].request.headers["Authorization"] == "Bearer test_bearer_token"
        # Check that User-Agent header is present and has correct format
        user_agent = responses.calls[0].request.headers.get("User-Agent")
        assert user_agent is not None
        assert user_agent.startswith("Lido-Oracle/v")

    @responses.activate
    def test_fetch__user_agent_header__is_present(self, lido_ipfs_provider):
        cid = CID("QmXvrr3gPtddcNrisH7i2nan9rY7v7RcxVQ9jjRreoWwRS")

        responses.add(
            responses.GET,
            f"https://ipfs-test.lido.fi/ipfs/{cid}",
            body=b"test content",
            status=200,
        )

        lido_ipfs_provider.fetch(cid)

        assert len(responses.calls) == 1
        headers = responses.calls[0].request.headers
        assert "User-Agent" in headers
        user_agent = headers["User-Agent"]
        assert user_agent.startswith("Lido-Oracle/v")

    @responses.activate
    def test_upload__user_agent_header__is_present(self, lido_ipfs_provider):
        content = b"test content for upload"
        expected_response = {"cid": "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"}

        responses.add(responses.POST, "https://ipfs-test.lido.fi/add", json=expected_response, status=200)

        lido_ipfs_provider.upload(content)

        assert len(responses.calls) == 1
        headers = responses.calls[0].request.headers
        assert "User-Agent" in headers
        user_agent = headers["User-Agent"]
        assert user_agent.startswith("Lido-Oracle/v")

    @responses.activate
    def test_fetch__request_fails__raises_fetch_error(self, lido_ipfs_provider):
        cid = CID("QmTestCid123")

        responses.add(
            responses.GET, f"https://ipfs-test.lido.fi/ipfs/{cid}", body=requests.ConnectionError("Network error")
        )

        with pytest.raises(FetchError):
            lido_ipfs_provider.fetch(cid)

    @responses.activate
    def test_fetch__http_error__raises_fetch_error(self, lido_ipfs_provider):
        cid = CID("QmTestCid123")

        responses.add(responses.GET, f"https://ipfs-test.lido.fi/ipfs/{cid}", status=404)

        with pytest.raises(FetchError):
            lido_ipfs_provider.fetch(cid)

    @responses.activate
    def test_upload__successful__returns_cid(self, lido_ipfs_provider):
        content = b"test content for upload"
        expected_response = {"cid": "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"}

        responses.add(responses.POST, "https://ipfs-test.lido.fi/add", json=expected_response, status=200)

        result = lido_ipfs_provider.upload(content)

        assert str(result) == "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"
        assert len(responses.calls) == 1

    @responses.activate
    def test_upload__request_fails__raises_upload_error(self, lido_ipfs_provider):
        content = b"test content"

        responses.add(
            responses.POST,
            "https://ipfs-test.lido.fi/add",
            body=requests.ConnectionError("Network error"),
        )

        with pytest.raises(UploadError):
            lido_ipfs_provider.upload(content)

    @responses.activate
    def test_upload__http_error__raises_upload_error(self, lido_ipfs_provider):
        content = b"test content"

        responses.add(responses.POST, "https://ipfs-test.lido.fi/add", status=500)

        with pytest.raises(UploadError):
            lido_ipfs_provider.upload(content)

    @responses.activate
    def test_upload__invalid_json__raises_upload_error(self, lido_ipfs_provider):
        content = b"test content"

        responses.add(responses.POST, "https://ipfs-test.lido.fi/add", body="invalid json", status=200)

        with pytest.raises(UploadError):
            lido_ipfs_provider.upload(content)

    @responses.activate
    def test_upload__missing_cid_key__raises_upload_error(self, lido_ipfs_provider):
        content = b"test content"
        invalid_response = {"wrong_key": "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"}

        responses.add(responses.POST, "https://ipfs-test.lido.fi/add", json=invalid_response, status=200)

        with pytest.raises(UploadError):
            lido_ipfs_provider.upload(content)

    @responses.activate
    def test_publish__successful__returns_cid(self, lido_ipfs_provider):
        content = b"test content for publish"
        upload_response = {"cid": "QmfEF32791rygeaCoTWMZ1fqswGXyahZHwTHPJsNPyXgzX"}

        responses.add(responses.POST, "https://ipfs-test.lido.fi/add", json=upload_response, status=200)

        result = lido_ipfs_provider.publish(content)

        assert str(result) == "QmfEF32791rygeaCoTWMZ1fqswGXyahZHwTHPJsNPyXgzX"
        assert len(responses.calls) == 1

    @responses.activate
    def test_fetch__cid_validation_fails__raises_validation_error(self, lido_ipfs_provider):
        # Use a valid CID format but with content that doesn't match
        cid = CID("QmPK1s3pNYLi9ERiq3BDxKa4XosgWwFRQUydHUtz4YgpqB")
        wrong_content = b"test content"

        responses.add(responses.GET, f"https://ipfs-test.lido.fi/ipfs/{cid}", body=wrong_content, status=200)

        with pytest.raises(CIDValidationError):
            lido_ipfs_provider.fetch(cid)

    @responses.activate
    def test_publish__cid_validation_fails__raises_validation_error(self, lido_ipfs_provider):
        content = b"test content"

        # Mock successful upload that returns wrong CID for this content
        upload_response = {"cid": "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"}

        responses.add(responses.POST, "https://ipfs-test.lido.fi/add", json=upload_response, status=200)

        with pytest.raises(CIDValidationError):
            lido_ipfs_provider.publish(content)
