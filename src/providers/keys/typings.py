from dataclasses import dataclass

from eth_typing import ChecksumAddress, HexStr

from src.utils.dataclass import FromResponse


@dataclass
class LidoKey(FromResponse):
    key: HexStr
    operatorIndex: int
    moduleAddress: ChecksumAddress
