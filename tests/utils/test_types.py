import pytest

from src.utils.types import bytes_to_hex_str, hex_str_to_bytes, is_4bytes_hex


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


@pytest.mark.unit
def test_is_4bytes_hex():
    assert is_4bytes_hex("0x00000000")
    assert is_4bytes_hex("0x02000000")
    assert is_4bytes_hex("0x02000000")
    assert is_4bytes_hex("0x30637624")

    assert not is_4bytes_hex("")
    assert not is_4bytes_hex("0x")
    assert not is_4bytes_hex("0x00")
    assert not is_4bytes_hex("0x01")
    assert not is_4bytes_hex("0x01")
    assert not is_4bytes_hex("0xgg")
    assert not is_4bytes_hex("0x111")
    assert not is_4bytes_hex("0x02000000ff")
