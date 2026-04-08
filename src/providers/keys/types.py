from dataclasses import dataclass
from typing import Self, cast

from eth_typing import ChecksumAddress, HexStr

from src.types import NodeOperatorId
from src.utils.abi import camel_to_snake
from src.utils.dataclass import FromResponse


@dataclass
class LidoKey(FromResponse):
    index: int
    key: HexStr
    deposit_signature: HexStr
    operator_index: NodeOperatorId
    used: bool
    module_address: ChecksumAddress

    @classmethod
    def from_response(cls, **kwargs) -> Self:
        response_lido_key = super().from_response(**{camel_to_snake(key): value for key, value in kwargs.items()})
        lido_key: Self = cast(Self, response_lido_key)
        lido_key.key = HexStr(lido_key.key.lower())  # pylint: disable=no-member
        return lido_key

@dataclass
class KeysApiStatus(FromResponse):
    app_version: str
    chain_id: int

    @classmethod
    def from_response(cls, **kwargs) -> Self:
        return super().from_response(**{camel_to_snake(key): value for key, value in kwargs.items()})
