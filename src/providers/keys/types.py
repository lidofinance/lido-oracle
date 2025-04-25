from dataclasses import dataclass
from typing import cast, Self

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

    @classmethod
    def from_response(cls, **kwargs) -> Self:
        response_lido_key = super().from_response(**kwargs)
        lido_key: Self = cast(Self, response_lido_key)
        lido_key.key = HexStr(lido_key.key.lower())  # pylint: disable=no-member
        return lido_key


@dataclass
class KeysApiStatus(FromResponse):
    appVersion: str
    chainId: int
