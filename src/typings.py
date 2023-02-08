from enum import StrEnum
from typing import TypedDict, NewType

from hexbytes import HexBytes


class OracleModule(StrEnum):
    ACCOUNTING = 'accounting'
    EJECTOR = 'ejector'


EpochNumber = NewType('EpochNumber', int)

StateRoot = NewType('StateRoot', HexBytes)
BlockRoot = NewType('BlockRoot', HexBytes)
SlotNumber = NewType('SlotNumber', int)

BlockHash = NewType('BlockHash', HexBytes)
BlockNumber = NewType('BlockNumber', int)


class BlockStamp(TypedDict):
    block_root: BlockRoot
    state_root: StateRoot
    slot_number: SlotNumber
    block_hash: BlockHash
    block_number: BlockNumber
