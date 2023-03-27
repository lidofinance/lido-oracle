import pytest

from src.utils.types import bytes_to_hex_str, hex_str_to_bytes


@pytest.mark.unit
def test_bytes_to_hex_str():
    assert bytes_to_hex_str(b"") == "0x"
    assert bytes_to_hex_str(b"\x00") == "0x00"
    assert bytes_to_hex_str(b"\x00\x01\x02") == "0x000102"


@pytest.mark.unit
def test_hex_str_to_bytes():
    assert hex_str_to_bytes("0x") == b""
    assert hex_str_to_bytes("0x00") == b"\x00"
    assert hex_str_to_bytes("0x000102") == b"\x00\x01\x02"
