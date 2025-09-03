def hex_str_to_bytes(hex_str: str) -> bytes:
    return bytes.fromhex(hex_str[2:]) if hex_str.startswith("0x") else bytes.fromhex(hex_str)
