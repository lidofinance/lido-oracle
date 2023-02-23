from enum import StrEnum
from typing import TypedDict, NewType

from hexbytes import HexBytes
from web3.types import Timestamp


class OracleModule(StrEnum):
    ACCOUNTING = 'accounting'
    EJECTOR = 'ejector'


EpochNumber = NewType('EpochNumber', int)

StateRoot = NewType('StateRoot', HexBytes)
SlotNumber = NewType('SlotNumber', int)

BlockHash = NewType('BlockHash', HexBytes)
BlockNumber = NewType('BlockNumber', int)


class BlockStamp(TypedDict):
    state_root: StateRoot
    slot_number: SlotNumber
    block_hash: BlockHash
    block_number: BlockNumber
    block_timestamp: Timestamp
    ref_slot: int
