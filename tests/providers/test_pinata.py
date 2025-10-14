import pytest
import responses

from src.providers.ipfs.pinata import Pinata
from src.providers.ipfs.types import FetchError


@pytest.fixture
def pinata_provider():
    return Pinata(
        jwt_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoxLCJ1c2VybmFtZSI6InRlc3QiLCJleHAiOjk5OTk5OTk5OTl9.Ps6jFKniFhNMYr_4WgETZP_LcXEfSzg3yUhNBn6Xgok",
        timeout=30,
        dedicated_gateway_url="https://dedicated.gateway.com",
        dedicated_gateway_token="dedicated_token_123",
    )


@pytest.mark.unit
@responses.activate
def test_fetch__dedicated_gateway_available__returns_content_from_dedicated(pinata_provider):
    responses.add(responses.GET, "https://dedicated.gateway.com/ipfs/QmTest123", body=b'test content', status=200)

    result = pinata_provider.fetch("QmTest123")

    assert result == b'test content'
    assert len(responses.calls) == 1
    request_headers = responses.calls[0].request.headers
    assert request_headers.get("x-pinata-gateway-token") == "dedicated_token_123"


@pytest.mark.unit
@responses.activate
def test_fetch__dedicated_gateway_fails_max_attempts__falls_back_to_public(pinata_provider):
    responses.add(
        responses.GET, "https://dedicated.gateway.com/ipfs/QmTest123", json={"error": "Gateway error"}, status=500
    )
    responses.add(
        responses.GET, "https://dedicated.gateway.com/ipfs/QmTest123", json={"error": "Gateway error"}, status=500
    )
    responses.add(responses.GET, "https://gateway.pinata.cloud/ipfs/QmTest123", body=b'public content', status=200)

    result = pinata_provider.fetch("QmTest123")

    assert result == b'public content'
    assert len(responses.calls) == 3
    assert responses.calls[0].request.headers.get("x-pinata-gateway-token") == "dedicated_token_123"
    assert responses.calls[1].request.headers.get("x-pinata-gateway-token") == "dedicated_token_123"
    assert "x-pinata-gateway-token" not in responses.calls[2].request.headers


@pytest.mark.unit
@responses.activate
def test_fetch__dedicated_gateway_fails_once__retries_and_succeeds(pinata_provider):
    responses.add(
        responses.GET, "https://dedicated.gateway.com/ipfs/QmTest123", json={"error": "First failure"}, status=500
    )
    responses.add(responses.GET, "https://dedicated.gateway.com/ipfs/QmTest123", body=b'dedicated success', status=200)

    result = pinata_provider.fetch("QmTest123")

    assert result == b'dedicated success'
    assert len(responses.calls) == 2


@pytest.mark.unit
@responses.activate
def test_fetch__both_gateways_fail__raises_fetch_error(pinata_provider):
    responses.add(
        responses.GET, "https://dedicated.gateway.com/ipfs/QmTest123", json={"error": "Dedicated error"}, status=500
    )
    responses.add(
        responses.GET, "https://dedicated.gateway.com/ipfs/QmTest123", json={"error": "Dedicated error"}, status=500
    )
    responses.add(
        responses.GET, "https://gateway.pinata.cloud/ipfs/QmTest123", json={"error": "Public error"}, status=500
    )

    with pytest.raises(FetchError):
        pinata_provider.fetch("QmTest123")

    assert len(responses.calls) == 3


@pytest.mark.unit
@responses.activate
def test_fetch__dedicated_gateway_429_rate_limit__retries_and_falls_back_to_public(pinata_provider):
    responses.add(
        responses.GET, "https://dedicated.gateway.com/ipfs/QmTest123", json={"error": "Rate limit exceeded"}, status=429
    )
    responses.add(
        responses.GET, "https://dedicated.gateway.com/ipfs/QmTest123", json={"error": "Rate limit exceeded"}, status=429
    )
    responses.add(responses.GET, "https://gateway.pinata.cloud/ipfs/QmTest123", body=b'public content', status=200)

    result = pinata_provider.fetch("QmTest123")

    assert result == b'public content'
    assert len(responses.calls) == 3
