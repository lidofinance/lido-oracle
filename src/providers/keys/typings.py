from dataclasses import dataclass

from eth_typing import Address
from hexbytes import HexBytes


@dataclass
class LidoKey:
    key: HexBytes
    depositSignature: HexBytes
    operatorIndex: int
    used: bool
    moduleAddress: Address
