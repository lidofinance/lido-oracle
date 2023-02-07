from enum import StrEnum
from typing import TypedDict, NewType

from hexbytes import HexBytes
from web3 import Web3 as _Web3

from src.web3_extentions import LidoContracts, TransactionUtils, ConsensusClientModule, KeysAPIClientModule


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


# Do not import those to avoid circular import
class Web3(_Web3):
    lido_contracts: LidoContracts
    transaction: TransactionUtils
    cc: ConsensusClientModule
    kac: KeysAPIClientModule
