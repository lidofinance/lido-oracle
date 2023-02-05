from typing import TypedDict

from eth_typing import Address
from hexbytes import HexBytes


class LidoKey(TypedDict):
    key: HexBytes
    depositSignature: HexBytes
    operatorIndex: int
    used: bool
    moduleAddress: Address
