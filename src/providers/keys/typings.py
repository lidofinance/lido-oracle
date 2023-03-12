from dataclasses import dataclass

from eth_typing import ChecksumAddress, HexStr

from src.utils.dataclass import FromResponse


@dataclass
class LidoKey(FromResponse):
    key: HexStr
    depositSignature: HexStr
    operatorIndex: int
    used: bool
    moduleAddress: ChecksumAddress
