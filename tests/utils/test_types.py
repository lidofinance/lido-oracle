import pytest

from src.utils.types import hex_str_to_bytes


@pytest.mark.unit
def test_hex_str_to_bytes():
    assert hex_str_to_bytes("") == b""
    assert hex_str_to_bytes("00") == b"\x00"
    assert hex_str_to_bytes("000102") == b"\x00\x01\x02"
    assert hex_str_to_bytes("0x") == b""
    assert hex_str_to_bytes("0x00") == b"\x00"
    assert hex_str_to_bytes("0x000102") == b"\x00\x01\x02"
