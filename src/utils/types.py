from eth_typing import HexStr


def bytes_to_hex_str(b: bytes) -> HexStr:
    return HexStr('0x' + b.hex())


def hex_str_to_bytes(hex_str: str) -> bytes:
    return bytes.fromhex(hex_str[2:]) if hex_str.startswith("0x") else bytes.fromhex(hex_str)


def is_4bytes_hex(s: str) -> bool:
    if not s.startswith("0x"):
        return False

    try:
        return len(bytes.fromhex(s[2:])) == 4
    except ValueError:
        return False
