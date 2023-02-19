from eth_typing import HexStr


def bytes_to_hex_str(b: bytes) -> HexStr:
    return HexStr('0x' + b.hex())
