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
        return Pinata(
            jwt_token=mock_jwt,
            timeout=30,
            dedicated_gateway_url="https://dedicated.gateway.com",
            dedicated_gateway_token="dedicated_token_123",
        )

    @responses.activate
    def test_fetch__valid_cid__returns_content_from_dedicated(self, pinata_provider):
        cid = CID("QmXvrr3gPtddcNrisH7i2nan9rY7v7RcxVQ9jjRreoWwRS")
        expected_content = b"test content"

        responses.add(
            responses.GET,
            "https://dedicated.gateway.com/ipfs/QmXvrr3gPtddcNrisH7i2nan9rY7v7RcxVQ9jjRreoWwRS",
            body=expected_content,
            status=200,
        )

        result = pinata_provider.fetch(cid)

        assert result == expected_content
        assert len(responses.calls) == 1
        request_headers = responses.calls[0].request.headers
        assert request_headers.get("x-pinata-gateway-token") == "dedicated_token_123"

    @responses.activate
    def test_fetch__request_fails__raises_fetch_error(self, pinata_provider):
        cid = CID("QmTestCid123")

        responses.add(
            responses.GET, f"{Pinata.PUBLIC_GATEWAY}/ipfs/QmTestCid123", body=requests.ConnectionError("Network error")
        )

        with pytest.raises(FetchError):
            pinata_provider.fetch(cid)

    @responses.activate
    def test_fetch__http_error__raises_fetch_error(self, pinata_provider):
        cid = CID("QmTestCid123")

        responses.add(responses.GET, f"{Pinata.PUBLIC_GATEWAY}/ipfs/QmTestCid123", status=404)

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
            f"{Pinata.PUBLIC_GATEWAY}/ipfs/QmTvfdWcdo964nULYqsDtLfUV7Gj7Yrob8msaeVJZo58zc",
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

    @responses.activate
    def test_fetch__dedicated_gateway_fails_max_attempts__falls_back_to_public(self, pinata_provider):
        cid = CID("QmZCCe4ykD1eeCogv43GYTdz8wGyBWaccoHA2KTpZCpvY3")
        responses.add(
            responses.GET,
            "https://dedicated.gateway.com/ipfs/QmZCCe4ykD1eeCogv43GYTdz8wGyBWaccoHA2KTpZCpvY3",
            json={"error": "Gateway error"},
            status=500,
        )
        responses.add(
            responses.GET,
            "https://dedicated.gateway.com/ipfs/QmZCCe4ykD1eeCogv43GYTdz8wGyBWaccoHA2KTpZCpvY3",
            json={"error": "Gateway error"},
            status=500,
        )
        responses.add(
            responses.GET,
            "https://gateway.pinata.cloud/ipfs/QmZCCe4ykD1eeCogv43GYTdz8wGyBWaccoHA2KTpZCpvY3",
            body=b'public content',
            status=200,
        )

        result = pinata_provider.fetch(cid)

        assert result == b'public content'
        assert len(responses.calls) == 3
        assert responses.calls[0].request.headers.get("x-pinata-gateway-token") == "dedicated_token_123"
        assert responses.calls[1].request.headers.get("x-pinata-gateway-token") == "dedicated_token_123"
        assert "x-pinata-gateway-token" not in responses.calls[2].request.headers

    @responses.activate
    def test_fetch__dedicated_gateway_fails_once__retries_and_succeeds(self, pinata_provider):
        cid = CID("QmSQBodZXntqeLDt2G22XQs6w8B4ibF29ShA2cQoURV4j2")
        responses.add(
            responses.GET,
            "https://dedicated.gateway.com/ipfs/QmSQBodZXntqeLDt2G22XQs6w8B4ibF29ShA2cQoURV4j2",
            json={"error": "First failure"},
            status=500,
        )
        responses.add(
            responses.GET,
            "https://dedicated.gateway.com/ipfs/QmSQBodZXntqeLDt2G22XQs6w8B4ibF29ShA2cQoURV4j2",
            body=b'dedicated success',
            status=200,
        )

        result = pinata_provider.fetch(cid)

        assert result == b'dedicated success'
        assert len(responses.calls) == 2

    @responses.activate
    def test_fetch__both_gateways_fail__raises_fetch_error(self, pinata_provider):
        cid = CID("QmZCCe4ykD1eeCogv43GYTdz8wGyBWaccoHA2KTpZCpvY3")
        responses.add(
            responses.GET,
            "https://dedicated.gateway.com/ipfs/QmZCCe4ykD1eeCogv43GYTdz8wGyBWaccoHA2KTpZCpvY3",
            json={"error": "Dedicated error"},
            status=500,
        )
        responses.add(
            responses.GET,
            "https://dedicated.gateway.com/ipfs/QmZCCe4ykD1eeCogv43GYTdz8wGyBWaccoHA2KTpZCpvY3",
            json={"error": "Dedicated error"},
            status=500,
        )
        responses.add(
            responses.GET,
            "https://gateway.pinata.cloud/ipfs/QmZCCe4ykD1eeCogv43GYTdz8wGyBWaccoHA2KTpZCpvY3",
            json={"error": "Public error"},
            status=500,
        )

        with pytest.raises(FetchError):
            pinata_provider.fetch(cid)

        assert len(responses.calls) == 3

    @responses.activate
    def test_fetch__dedicated_gateway_429_rate_limit__retries_and_falls_back_to_public(self, pinata_provider):
        cid = CID("QmZCCe4ykD1eeCogv43GYTdz8wGyBWaccoHA2KTpZCpvY3")
        responses.add(
            responses.GET,
            "https://dedicated.gateway.com/ipfs/QmZCCe4ykD1eeCogv43GYTdz8wGyBWaccoHA2KTpZCpvY3",
            json={"error": "Rate limit exceeded"},
            status=429,
        )
        responses.add(
            responses.GET,
            "https://dedicated.gateway.com/ipfs/QmZCCe4ykD1eeCogv43GYTdz8wGyBWaccoHA2KTpZCpvY3",
            json={"error": "Rate limit exceeded"},
            status=429,
        )
        responses.add(
            responses.GET,
            "https://gateway.pinata.cloud/ipfs/QmZCCe4ykD1eeCogv43GYTdz8wGyBWaccoHA2KTpZCpvY3",
            body=b'public content',
            status=200,
        )

        result = pinata_provider.fetch(cid)

        assert result == b'public content'
        assert len(responses.calls) == 3
