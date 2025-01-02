from dataclasses import dataclass
from typing import Type, cast, Self

from eth_typing import ChecksumAddress, HexStr

from src.types import NodeOperatorId
from src.utils.dataclass import FromResponse, T


@dataclass
class LidoKey(FromResponse):
    key: HexStr
    depositSignature: HexStr
    operatorIndex: NodeOperatorId
    used: bool
    moduleAddress: ChecksumAddress

    @classmethod
    def from_response(cls, **kwargs) -> Self:
        # Example: Modify kwargs or add logging
        lido_key = super().from_response(**kwargs)
        lido_key = cast(LidoKey, lido_key)
        lido_key.key = HexStr(lido_key.key.lower())
        return lido_key


@dataclass
class KeysApiStatus(FromResponse):
    appVersion: str
    chainId: int
