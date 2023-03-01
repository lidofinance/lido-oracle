from dataclasses import dataclass

from eth_typing import Address, HexStr


@dataclass
class LidoKey:
    key: HexStr
    depositSignature: HexStr
    operatorIndex: int
    used: bool
    moduleAddress: Address
