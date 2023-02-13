from dataclasses import dataclass

from eth_typing import Address
from hexbytes import HexBytes

from src.providers.consensus.typings import Validator


@dataclass
class LidoKey:
    key: HexBytes
    depositSignature: HexBytes
    operatorIndex: int
    used: bool
    moduleAddress: Address


@dataclass
class LidoValidator:
    key: LidoKey
    validator: Validator
