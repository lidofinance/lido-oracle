from dataclasses import dataclass

from eth_typing import HexAddress, HexStr


@dataclass
class LidoKey:
    key: HexStr
    depositSignature: HexStr
    operatorIndex: int
    used: bool
    moduleAddress: HexAddress
