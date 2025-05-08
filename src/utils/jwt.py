import json
from typing import Any

from src.utils.base64 import decode_base64url


def validate_jwt(token: Any):
    """Validates a JWT token's structure without verifying the signature"""

    if not isinstance(token, str):
        raise ValueError("Invalid JWT: Token must be a string")

    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format: Token must have 3 parts separated by dots")

    header_b64, payload_b64, _ = parts

    try:
        header_json = decode_base64url(header_b64)
    except ValueError as e:
        raise ValueError("Invalid JWT format: Failed to decode header") from e

    try:
        header = json.loads(header_json)
        if not isinstance(header, dict):
            raise ValueError("Invalid JWT format: Header is not a JSON object")
    except json.JSONDecodeError as e:
        raise ValueError("Invalid JWT format: Cannot parse header JSON") from e

    try:
        payload_json = decode_base64url(payload_b64)
    except ValueError as e:
        raise ValueError("Invalid JWT format: Failed to decode payload") from e

    try:
        payload = json.loads(payload_json)
        if not isinstance(payload, dict):
            raise ValueError("Invalid JWT format: Payload is not a JSON object")
    except json.JSONDecodeError as e:
        raise ValueError("Invalid JWT format: Cannot parse payload JSON") from e
