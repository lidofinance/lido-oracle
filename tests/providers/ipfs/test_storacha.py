import pytest
import requests
import responses

from src.providers.ipfs.storacha import Storacha
from src.providers.ipfs.cid import CID
from src.providers.ipfs.types import FetchError, UploadError, CIDValidationError


@pytest.mark.unit
class TestStoracha:

    @pytest.fixture
    def storacha_provider(self):
        return Storacha(
            auth_secret="test_secret", authorization="Bearer test_token", space_did="did:key:test", timeout=30
        )

    @responses.activate
    def test_fetch__valid_cid__returns_content(self, storacha_provider):
        cid = CID("QmXvrr3gPtddcNrisH7i2nan9rY7v7RcxVQ9jjRreoWwRS")
        expected_content = b"test content"

        responses.add(
            responses.GET,
            f"{Storacha.GATEWAY_URL}{cid}",
            body=expected_content,
            status=200,
        )

        result = storacha_provider.fetch(cid)

        assert result == expected_content
        assert len(responses.calls) == 1

    @responses.activate
    def test_fetch__request_fails__raises_fetch_error(self, storacha_provider):
        cid = CID("QmTestCid123")

        responses.add(
            responses.GET, f"{Storacha.GATEWAY_URL}QmTestCid123", body=requests.ConnectionError("Network error")
        )

        with pytest.raises(FetchError):
            storacha_provider.fetch(cid)

    @responses.activate
    def test_fetch__http_error__raises_fetch_error(self, storacha_provider):
        cid = CID("QmTestCid123")

        responses.add(responses.GET, f"{Storacha.GATEWAY_URL}QmTestCid123", status=404)

        with pytest.raises(FetchError):
            storacha_provider.fetch(cid)

    @responses.activate
    def test_publish__successful_upload_with_store_upload__returns_root_cid(self, storacha_provider):
        content = b"mock car content for upload test"

        store_response_data = [
            {
                "p": {
                    "out": {
                        "ok": {
                            "status": "upload",
                            "url": f"{Storacha.BRIDGE_URL}/upload/test123",
                            "headers": {"X-Upload-Header": "value"},
                        }
                    }
                }
            }
        ]

        upload_add_response_data = [
            {"p": {"out": {"ok": {"root": {"/": "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"}}}}}
        ]

        responses.add(responses.POST, Storacha.BRIDGE_URL, json=store_response_data, status=200)

        responses.add(responses.PUT, f"{Storacha.BRIDGE_URL}/upload/test123", status=200)

        responses.add(responses.POST, Storacha.BRIDGE_URL, json=upload_add_response_data, status=200)

        result = storacha_provider.publish(content)

        assert str(result) == "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"
        assert len(responses.calls) == 3

    @responses.activate
    def test_publish__store_returns_error__raises_upload_error(self, storacha_provider):
        content = b"mock car content for upload test"

        error_response_data = [{"p": {"out": {"error": {"name": "StoreError", "message": "Storage failed"}}}}]

        responses.add(responses.POST, Storacha.BRIDGE_URL, json=error_response_data, status=200)

        with pytest.raises(UploadError, match="Storacha store/add error"):
            storacha_provider.publish(content)

    @responses.activate
    def test_publish__upload_add_fails__raises_upload_error(self, storacha_provider):
        content = b"mock car content for upload test"

        store_response_data = [
            {
                "p": {
                    "out": {
                        "ok": {
                            "status": "upload",
                            "url": f"{Storacha.BRIDGE_URL}/upload/test123",
                            "headers": {"X-Upload-Header": "value"},
                        }
                    }
                }
            }
        ]

        responses.add(responses.POST, Storacha.BRIDGE_URL, json=store_response_data, status=200)

        responses.add(responses.PUT, f"{Storacha.BRIDGE_URL}/upload/test123", status=200)

        responses.add(responses.POST, Storacha.BRIDGE_URL, body=requests.ConnectionError("Upload/add failed"))

        with pytest.raises(UploadError, match="Upload/add request failed"):
            storacha_provider.publish(content)

    @responses.activate
    def test_publish__store_status_done__skips_upload_request(self, storacha_provider):
        content = b"mock car content for upload test"

        store_response_data = [{"p": {"out": {"ok": {"status": "done"}}}}]

        upload_add_response_data = [
            {"p": {"out": {"ok": {"root": {"/": "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"}}}}}
        ]

        responses.add(responses.POST, Storacha.BRIDGE_URL, json=store_response_data, status=200)

        responses.add(responses.POST, Storacha.BRIDGE_URL, json=upload_add_response_data, status=200)

        result = storacha_provider.publish(content)

        assert str(result) == "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"
        assert len(responses.calls) == 2

    @responses.activate
    def test_fetch__cid_validation_fails__raises_validation_error(self, storacha_provider):
        # Use a valid CID format but with content that doesn't match
        cid = CID("QmPK1s3pNYLi9ERiq3BDxKa4XosgWwFRQUydHUtz4YgpqB")
        wrong_content = b"test content"

        responses.add(responses.GET, f"{Storacha.GATEWAY_URL}{cid}", body=wrong_content, status=200)

        with pytest.raises(CIDValidationError):
            storacha_provider.fetch(cid)

    @responses.activate
    def test_publish__cid_validation_fails__raises_validation_error(self, storacha_provider):
        content = b"test content"

        # Mock successful upload that returns wrong CID
        store_response_data = [
            {
                "p": {
                    "out": {
                        "ok": {
                            "status": "upload",
                            "url": f"{Storacha.BRIDGE_URL}/upload/test123",
                            "headers": {"X-Upload-Header": "value"},
                        }
                    }
                }
            }
        ]

        upload_add_response_data = [
            {"p": {"out": {"ok": {"root": {"/": "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"}}}}}
        ]

        responses.add(responses.POST, Storacha.BRIDGE_URL, json=store_response_data, status=200)
        responses.add(responses.PUT, f"{Storacha.BRIDGE_URL}/upload/test123", status=200)
        responses.add(responses.POST, Storacha.BRIDGE_URL, json=upload_add_response_data, status=200)

        with pytest.raises(CIDValidationError):
            storacha_provider.publish(content)

    @responses.activate
    def test_publish__upload_put_fails__logs_safely_without_sensitive_url(self, storacha_provider, caplog):
        content = b"mock car content for upload test"

        # URL with sensitive AWS auth tokens (similar to real Storacha response)
        sensitive_upload_url = "https://carpark-prod-0.s3.us-west-2.amazonaws.com/test/test.car?X-Amz-Credential=SENSITIVE&X-Amz-Security-Token=SENSITIVE_TOKEN"

        store_response_data = [
            {
                "p": {
                    "out": {
                        "ok": {
                            "status": "upload",
                            "url": sensitive_upload_url,
                            "headers": {"content-length": "12345"},
                        }
                    }
                }
            }
        ]

        responses.add(responses.POST, Storacha.BRIDGE_URL, json=store_response_data, status=200)
        responses.add(responses.PUT, sensitive_upload_url, status=500)

        with pytest.raises(UploadError, match="Upload request failed"):
            storacha_provider.publish(content)

        log_records = [record.message for record in caplog.records]
        log_content = ' '.join(log_records)

        assert "X-Amz-Credential" not in log_content
        assert "X-Amz-Security-Token" not in log_content
        assert "SENSITIVE" not in log_content
        assert "carpark-prod-0.s3.us-west-2.amazonaws.com" not in log_content

        assert "Upload request failed" in log_content
        assert "HTTPError" in log_content
        assert "500" in log_content
