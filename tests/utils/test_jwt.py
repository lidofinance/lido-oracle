"""Test for utils.base64 module"""

import base64

import pytest

from src.utils.jwt import validate_jwt


@pytest.mark.unit
def test_valid_token():
    """Test valid token is accepted"""
    validate_jwt(
        ".".join(
            [
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
                "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiYWRtaW4iOnRydWUsImlhdCI6MTUxNjIzOTAyMn0",
                "KMUFsIDTnFmyG3nMiGM6H9FNFUROf3wh7SmqJp-QV30",
            ]
        )
    )


@pytest.mark.unit
def test_invalid_token_not_string():
    """Test non-string input raises ValueError."""
    with pytest.raises(ValueError, match="Token must be a string"):
        validate_jwt(12345)
    with pytest.raises(ValueError, match="Token must be a string"):
        validate_jwt(None)


@pytest.mark.unit
def test_invalid_token_wrong_parts():
    """Test token string with incorrect number of segments."""
    with pytest.raises(ValueError, match="Token must have 3 parts"):
        validate_jwt("header.payload")
    with pytest.raises(ValueError, match="Token must have 3 parts"):
        validate_jwt("header.payload.sig.extra")


@pytest.mark.unit
def test_invalid_token_bad_payload_encoding():
    """Test token with invalid Base64Url in the payload segment."""
    token = "header.payload_is_not_base64!!.signature"
    with pytest.raises(ValueError, match="Failed to decode header"):
        validate_jwt(token)


@pytest.mark.unit
def test_invalid_token_header_not_json():
    """Test token where header decodes but isn't valid JSON."""
    with pytest.raises(ValueError, match="Cannot parse header JSON"):
        validate_jwt(f"{base64.b64encode(b'not json').decode('UTF-8')}.payload.sign")


@pytest.mark.unit
def test_invalid_token_header_not_json_object():
    """Test token where header decodes but isn't valid JSON."""
    with pytest.raises(ValueError, match="Header is not a JSON object"):
        validate_jwt(f"{base64.b64encode(b'[1,2,3]').decode('UTF-8')}.payload.sign")


@pytest.mark.unit
def test_invalid_token_payload_not_json():
    """Test token where payload decodes but isn't valid JSON."""
    with pytest.raises(ValueError, match="Cannot parse payload JSON"):
        validate_jwt(f"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.{base64.b64encode(b'not json').decode('UTF-8')}.sign")


@pytest.mark.unit
def test_invalid_token_payload_not_json_object():
    """Test token where payload is valid JSON but not an object/dict."""
    with pytest.raises(ValueError, match="Payload is not a JSON object"):
        validate_jwt(f"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.{base64.b64encode(b'[1,2,3]').decode('UTF-8')}.sign")
