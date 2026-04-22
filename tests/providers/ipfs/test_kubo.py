from unittest.mock import patch

import pytest
import requests
import responses

from src.providers.ipfs.cid import CID
from src.providers.ipfs.filebase import Filebase
from src.providers.ipfs.kubo import Kubo
from src.providers.ipfs.types import FetchError, PinError, UploadError


@pytest.mark.unit
class TestKubo:
    @pytest.fixture
    def kubo_provider(self):
        return Kubo(host="http://localhost", rpc_port=5001, timeout=30)

    @pytest.fixture
    def kubo_provider_with_token(self):
        return Kubo(host="http://localhost", rpc_port=5001, timeout=30, token="test_bearer_token")

    @responses.activate
    def test_fetch__valid_cid__returns_content(self, kubo_provider):
        cid = CID("QmXvrr3gPtddcNrisH7i2nan9rY7v7RcxVQ9jjRreoWwRS")
        expected_content = b"test content"

        responses.add(
            responses.POST,
            "http://localhost:5001/api/v0/cat",
            body=expected_content,
            status=200,
        )

        result = kubo_provider.fetch(cid)

        assert result == expected_content
        assert len(responses.calls) == 1
        assert f"arg={cid}" in responses.calls[0].request.url

    @responses.activate
    def test_fetch__token_is_set__includes_authorization_header(self, kubo_provider_with_token):
        cid = CID("QmXvrr3gPtddcNrisH7i2nan9rY7v7RcxVQ9jjRreoWwRS")

        responses.add(
            responses.POST,
            "http://localhost:5001/api/v0/cat",
            body=b"test content",
            status=200,
        )

        kubo_provider_with_token.fetch(cid)

        assert len(responses.calls) == 1
        assert responses.calls[0].request.headers["Authorization"] == "Bearer test_bearer_token"

    @responses.activate
    def test_fetch__request_fails__raises_fetch_error(self, kubo_provider):
        cid = CID("QmTestCid123")

        responses.add(
            responses.POST,
            "http://localhost:5001/api/v0/cat",
            body=requests.ConnectionError("Network error"),
        )

        with pytest.raises(FetchError):
            kubo_provider.fetch(cid)

    @responses.activate
    def test_fetch__http_error__raises_fetch_error(self, kubo_provider):
        cid = CID("QmTestCid123")

        responses.add(responses.POST, "http://localhost:5001/api/v0/cat", status=404)

        with pytest.raises(FetchError):
            kubo_provider.fetch(cid)

    @responses.activate
    def test_upload__successful__returns_cid(self, kubo_provider):
        content = b"mock car content for upload test"
        expected_response = {"Hash": "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"}

        responses.add(
            responses.POST,
            "http://localhost:5001/api/v0/add",
            json=expected_response,
            status=200,
        )

        result = kubo_provider.upload(content, name="report.car")

        assert str(result) == "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"
        assert len(responses.calls) == 1
        request_url = responses.calls[0].request.url
        assert "chunker=size-262144" in request_url
        assert "hash=sha2-256" in request_url
        assert "cid-version=0" in request_url
        assert "trickle=false" in request_url
        assert "raw-leaves=false" in request_url

    @responses.activate
    def test_upload__token_is_set__includes_authorization_header(self, kubo_provider_with_token):
        content = b"mock car content for upload test"
        expected_response = {"Hash": "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"}

        responses.add(
            responses.POST,
            "http://localhost:5001/api/v0/add",
            json=expected_response,
            status=200,
        )

        kubo_provider_with_token.upload(content)

        assert len(responses.calls) == 1
        assert responses.calls[0].request.headers["Authorization"] == "Bearer test_bearer_token"

    @responses.activate
    def test_upload__request_fails__raises_upload_error(self, kubo_provider):
        content = b"mock car content for upload test"

        responses.add(
            responses.POST,
            "http://localhost:5001/api/v0/add",
            body=requests.ConnectionError("Network error"),
        )

        with pytest.raises(UploadError):
            kubo_provider.upload(content)

    @responses.activate
    def test_upload__http_error__raises_upload_error(self, kubo_provider):
        content = b"mock car content for upload test"

        responses.add(responses.POST, "http://localhost:5001/api/v0/add", status=500)

        with pytest.raises(UploadError):
            kubo_provider.upload(content)

    @responses.activate
    def test_upload__invalid_json__raises_upload_error(self, kubo_provider):
        content = b"mock car content for upload test"

        responses.add(responses.POST, "http://localhost:5001/api/v0/add", body="invalid json", status=200)

        with pytest.raises(UploadError):
            kubo_provider.upload(content)

    @responses.activate
    def test_upload__missing_hash_key__raises_upload_error(self, kubo_provider):
        content = b"mock car content for upload test"
        invalid_response = {"WrongKey": "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"}

        responses.add(
            responses.POST,
            "http://localhost:5001/api/v0/add",
            json=invalid_response,
            status=200,
        )

        with pytest.raises(UploadError):
            kubo_provider.upload(content)

    @responses.activate
    @patch("src.variables.IPFS_VALIDATE_CID", False)
    def test_publish__successful__returns_cid(self, kubo_provider):
        content = b"mock car content for upload test"
        upload_response = {"Hash": "QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc"}
        cid = CID("QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc")

        responses.add(responses.POST, "http://localhost:5001/api/v0/add", json=upload_response, status=200)
        responses.add(
            responses.POST,
            "http://localhost:5001/api/v0/pin/add",
            json={"Pins": [str(cid)]},
            status=200,
        )

        result = kubo_provider.publish(content)

        assert str(result) == str(cid)
        assert len(responses.calls) == 2

    @responses.activate
    def test_pin__successful__does_not_raise(self, kubo_provider):
        cid = CID("QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc")

        responses.add(
            responses.POST,
            "http://localhost:5001/api/v0/pin/add",
            json={"Pins": [str(cid)]},
            status=200,
        )

        kubo_provider.pin(cid)

        assert len(responses.calls) == 1
        assert f"arg={cid}" in responses.calls[0].request.url

    @responses.activate
    def test_pin__token_is_set__includes_authorization_header(self, kubo_provider_with_token):
        cid = CID("QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc")

        responses.add(
            responses.POST,
            "http://localhost:5001/api/v0/pin/add",
            json={"Pins": [str(cid)]},
            status=200,
        )

        kubo_provider_with_token.pin(cid)

        assert len(responses.calls) == 1
        assert responses.calls[0].request.headers["Authorization"] == "Bearer test_bearer_token"

    @responses.activate
    def test_pin__request_fails__raises_pin_error(self, kubo_provider):
        cid = CID("QmTestCid123")

        responses.add(
            responses.POST,
            "http://localhost:5001/api/v0/pin/add",
            body=requests.ConnectionError("Network error"),
        )

        with pytest.raises(PinError):
            kubo_provider.pin(cid)

    @responses.activate
    def test_pin__http_error__raises_pin_error(self, kubo_provider):
        cid = CID("QmTestCid123")

        responses.add(responses.POST, "http://localhost:5001/api/v0/pin/add", status=500)

        with pytest.raises(PinError):
            kubo_provider.pin(cid)

    @responses.activate
    def test_pin__invalid_json__raises_upload_error(self, kubo_provider):
        cid = CID("QmTestCid123")

        responses.add(responses.POST, "http://localhost:5001/api/v0/pin/add", body="invalid json", status=200)

        with pytest.raises(UploadError):
            kubo_provider.pin(cid)

    @responses.activate
    def test_pin__missing_pins_key__raises_upload_error(self, kubo_provider):
        cid = CID("QmTestCid123")

        responses.add(responses.POST, "http://localhost:5001/api/v0/pin/add", json={"WrongKey": []}, status=200)

        with pytest.raises(UploadError):
            kubo_provider.pin(cid)

    @responses.activate
    def test_pin__empty_pins_list__raises_upload_error(self, kubo_provider):
        cid = CID("QmTestCid123")

        responses.add(responses.POST, "http://localhost:5001/api/v0/pin/add", json={"Pins": []}, status=200)

        with pytest.raises(UploadError):
            kubo_provider.pin(cid)

    @responses.activate
    def test_pin__unexpected_cid__raises_pin_error(self, kubo_provider):
        cid = CID("QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc")

        responses.add(
            responses.POST,
            "http://localhost:5001/api/v0/pin/add",
            json={"Pins": ["QmPK1s3pNYLi9ERiq3BDxKa4XosgWwFRQUydHUtz4YgpqB"]},
            status=200,
        )

        with pytest.raises(PinError):
            kubo_provider.pin(cid)


@pytest.mark.unit
class TestFilebase:
    def test_init__forwards_token_to_kubo(self):
        provider = Filebase(host="https://filebase.example", rpc_port=5001, timeout=30, token="filebase_token")

        assert provider.token == "filebase_token"
        assert provider._headers() == {"Authorization": "Bearer filebase_token"}
