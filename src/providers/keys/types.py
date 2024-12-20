from dataclasses import dataclass

from eth_typing import ChecksumAddress, HexStr

from src.types import NodeOperatorId
from src.utils.dataclass import FromResponse


@dataclass
class LidoKey(FromResponse):
    key: HexStr
    depositSignature: HexStr
    operatorIndex: NodeOperatorId
    used: bool
    moduleAddress: ChecksumAddress


@dataclass
class KeysApiStatus(FromResponse):
    appVersion: str
    chainId: int
