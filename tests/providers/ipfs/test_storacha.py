import pytest
from unittest.mock import patch, MagicMock
import requests
import responses

from src.providers.ipfs.storacha import Storacha
from src.providers.ipfs.cid import CID
from src.providers.ipfs.types import FetchError, UploadError


@pytest.mark.unit
class TestStoracha:

    @pytest.fixture
    def mock_car_data(self):
        return (
            b"mock_car_bytes",
            "QmPK1s3pNYLi9ERiq3BDxKa4XosgWwFRQUydHUtz4YgpqB",
            "QmbWqxBEKC3P8tqsKc98xmWNzrzDtRLMiMPL8wBuTGsMnR",
            100,
        )

    @pytest.fixture
    def storacha_provider(self, mock_car_data):
        provider = Storacha(
            auth_secret="test_secret", authorization="Bearer test_token", space_did="did:key:test", timeout=30
        )
        with patch.object(provider, 'car_converter', MagicMock()) as mock_car_converter:
            mock_car_converter.create_car_from_data.return_value = mock_car_data
            yield provider

    @responses.activate
    def test_fetch__valid_cid__returns_content(self, storacha_provider):
        cid = CID("QmTestCid123")
        expected_content = b"test content"

        responses.add(responses.GET, f"{Storacha.GATEWAY_URL}QmTestCid123", body=expected_content, status=200)

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
    def test_publish__successful_upload_with_store_upload__returns_root_cid(self, storacha_provider, mock_car_data):
        content = b"test content"

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
            {"p": {"out": {"ok": {"root": {"/": "QmPK1s3pNYLi9ERiq3BDxKa4XosgWwFRQUydHUtz4YgpqB"}}}}}
        ]

        responses.add(responses.POST, Storacha.BRIDGE_URL, json=store_response_data, status=200)

        responses.add(responses.PUT, f"{Storacha.BRIDGE_URL}/upload/test123", status=200)

        responses.add(responses.POST, Storacha.BRIDGE_URL, json=upload_add_response_data, status=200)

        result = storacha_provider.publish(content)

        assert str(result) == "QmPK1s3pNYLi9ERiq3BDxKa4XosgWwFRQUydHUtz4YgpqB"
        assert len(responses.calls) == 3

    @responses.activate
    def test_publish__store_returns_error__raises_upload_error(self, storacha_provider, mock_car_data):
        content = b"test content"

        error_response_data = [{"p": {"out": {"error": {"name": "StoreError", "message": "Storage failed"}}}}]

        responses.add(responses.POST, Storacha.BRIDGE_URL, json=error_response_data, status=200)

        with pytest.raises(UploadError, match="Storacha store/add error"):
            storacha_provider.publish(content)

    @responses.activate
    def test_publish__upload_add_fails__raises_upload_error(self, storacha_provider, mock_car_data):
        content = b"test content"

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
    def test_publish__store_status_done__skips_upload_request(self, storacha_provider, mock_car_data):
        content = b"test content"

        store_response_data = [{"p": {"out": {"ok": {"status": "done"}}}}]

        upload_add_response_data = [
            {"p": {"out": {"ok": {"root": {"/": "QmPK1s3pNYLi9ERiq3BDxKa4XosgWwFRQUydHUtz4YgpqB"}}}}}
        ]

        responses.add(responses.POST, Storacha.BRIDGE_URL, json=store_response_data, status=200)

        responses.add(responses.POST, Storacha.BRIDGE_URL, json=upload_add_response_data, status=200)

        result = storacha_provider.publish(content)

        assert str(result) == "QmPK1s3pNYLi9ERiq3BDxKa4XosgWwFRQUydHUtz4YgpqB"
        assert len(responses.calls) == 2
