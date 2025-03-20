"""
https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#bls-signatures
"""

import re

from eth_typing import HexStr
from web3 import Web3


BLS_PUBLIC_KEY_SIZE = 48
BLS_SIGNATURE_SIZE = 96

BLS_PUBLIC_KEY_PATTERN = re.compile(r'^0x[0-9a-fA-F]{96}$')
BLS_SIGNATURE_PATTERN = re.compile(r'^0x[0-9a-fA-F]{192}$')

w3 = Web3()


def _is_valid_hex_format(value: HexStr, pattern: re.Pattern, expected_bytes: int) -> bool:
    if not isinstance(value, str) or pattern.match(value) is None:
        return False
    try:
        bytes_value = w3.to_bytes(hexstr=value)
        return len(bytes_value) == expected_bytes
    except ValueError:
        return False


def is_valid_bls_public_key(value: HexStr) -> bool:
    return _is_valid_hex_format(value, BLS_PUBLIC_KEY_PATTERN, BLS_PUBLIC_KEY_SIZE)


def is_valid_bls_signature(value: HexStr) -> bool:
    return _is_valid_hex_format(value, BLS_SIGNATURE_PATTERN, BLS_SIGNATURE_SIZE)
