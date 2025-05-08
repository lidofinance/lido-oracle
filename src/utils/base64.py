import base64
import binascii


def decode_base64url(data: str) -> str:
    """
    Decodes a base64url encoded string to a UTF-8 string.
    Handles padding and URL-safe character replacements.
    """

    # Replace base64url specific characters back to standard base64.
    data = data.replace("-", "+").replace("_", "/")
    # Calculate and add necessary padding (expected by b64decode).
    padding = "=" * ((4 - len(data) % 4) % 4)
    data += padding
    try:
        return base64.b64decode(data).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as e:
        raise ValueError("base64url decoding failed") from e
    except Exception as e:
        raise ValueError("An unexpected error occurred during base64url decoding") from e
