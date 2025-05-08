"""Test for utils.base64 module"""

import pytest

from src.utils.base64 import decode_base64url


@pytest.mark.unit
def test_empty_string():
    """Test decoding an empty string."""
    assert decode_base64url("") == ""


@pytest.mark.unit
@pytest.mark.parametrize(
    "encoded, expected",
    [
        # No padding needed (length multiple of 4)
        ("TWFuPw", "Man?"),  # "Man?"
        ("SGVsbG8h", "Hello!"),  # "Hello!"
        (
            "eyJ0eXAiOiJKV1QiLCAiYWxnIjoiSFMyNTYifQ",  # '{"typ":"JWT", "alg":"HS256"}'
            '{"typ":"JWT", "alg":"HS256"}',
        ),
        # Two padding chars needed (len % 4 == 2)
        ("Zg", "f"),  # "f"
        ("TQ", "M"),  # "M"
        # One padding char needed (len % 4 == 3)
        ("Zm8", "fo"),  # "fo"
        ("TWE", "Ma"),  # "Ma"
        # Including URL-safe characters
        (
            "eyJ1c2VyX2lkIjogMTIzLCAicm9sZXMiOiBbImFkbWluIiwgImRldiJdfQ",  # JSON payload
            '{"user_id": 123, "roles": ["admin", "dev"]}',
        ),
        # RFC4648 vectors (UTF-8 safe)
        ("Zm9v", "foo"),
        ("Zm9vYg", "foob"),
        ("Zm9vYmE", "fooba"),
        ("Zm9vYmFy", "foobar"),
    ],
)
def test_valid_decoding(encoded, expected):
    """Test various valid base64url strings."""
    assert decode_base64url(encoded) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "encoded_with_padding, expected",
    [
        # Correct padding explicitly provided
        ("Zg==", "f"),
        ("Zm8=", "fo"),
        ("Zm9vYg==", "foob"),
        ("Zm9vYmE=", "fooba"),
        ("Zm9v", "foo"),  # Case with no padding needed should still work
    ],
)
def test_handling_existing_correct_padding(encoded_with_padding, expected):
    """Test if the function handles optional but correct padding."""
    assert decode_base64url(encoded_with_padding) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid_input",
    [
        "Invalid$Char",  # Invalid character '$'
        "Space Here",  # Space is invalid
        "Dot.There",  # Dot is invalid
        "Zm=vYmFy",  # Equals sign in the middle
    ],
)
def test_invalid_characters(invalid_input):
    """Test strings with characters outside the Base64Url alphabet."""
    with pytest.raises(ValueError, match="base64url decoding failed"):
        decode_base64url(invalid_input)


@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid_length_input",
    [
        "A",  # Length 1 (mod 4 == 1)
        "ABCDE",  # Length 5 (mod 4 == 1)
    ],
)
def test_invalid_length_mod_4_is_1(invalid_length_input):
    """Test strings with invalid length (mod 4 == 1)."""
    # Base64(url) encoded strings cannot have length % 4 == 1 before padding
    with pytest.raises(ValueError, match="base64url decoding failed"):
        decode_base64url(invalid_length_input)


@pytest.mark.unit
def test_non_utf8_result():
    """Test decoding data that isn't valid UTF-8."""
    # RFC 4648 vector: \xfb\xff\xbf -> "-_-_" (Base64Url) -> invalid UTF-8 bytes
    encoded_non_utf8_rfc = "-_-_"
    with pytest.raises(ValueError, match="base64url decoding failed"):
        decode_base64url(encoded_non_utf8_rfc)

    # Byte 0xFF ('/w' in std base64, '_w' in urlsafe) -> needs '==' padding
    encoded_non_utf8_ff = "_w"
    with pytest.raises(ValueError, match="base64url decoding failed"):
        decode_base64url(encoded_non_utf8_ff)
