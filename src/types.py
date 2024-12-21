from dataclasses import dataclass
from enum import StrEnum, auto
from typing import NewType

from eth_typing import BlockNumber, ChecksumAddress, HexStr
from web3.types import Timestamp, Wei


class OracleModule(StrEnum):
    ACCOUNTING = 'accounting'
    EJECTOR = 'ejector'
    CHECK = 'check'
    CSM = 'csm'


EpochNumber = NewType('EpochNumber', int)
FrameNumber = NewType('FrameNumber', int)
StateRoot = NewType('StateRoot', HexStr)
BlockRoot = NewType('BlockRoot', HexStr)
SlotNumber = NewType('SlotNumber', int)

StakingModuleAddress = NewType('StakingModuleAddress', ChecksumAddress)
StakingModuleId = NewType('StakingModuleId', int)
NodeOperatorId = NewType('NodeOperatorId', int)
NodeOperatorGlobalIndex = tuple[StakingModuleId, NodeOperatorId]

BlockHash = NewType('BlockHash', HexStr)

Gwei = NewType('Gwei', int)

ValidatorIndex = NewType('ValidatorIndex', int)
CommitteeIndex = NewType('CommitteeIndex', int)

FinalizationBatches = NewType('FinalizationBatches', list[int])
WithdrawalVaultBalance = NewType('WithdrawalVaultBalance', Wei)
ELVaultBalance = NewType('ELVaultBalance', Wei)

type OperatorsValidatorCount = dict[NodeOperatorGlobalIndex, int]


class _Fork(StrEnum):
    """We store fork versions as an enum of hex encoded 4 bytes, so the values are comparable as strings"""

    GENESIS = auto()
    ALTAIR = auto()
    BELLATRIX = auto()
    CAPELLA = auto()
    DENEB = auto()
    ELECTRA = auto()


type Fork = _Fork


@dataclass(frozen=True)
class BlockStamp:
    state_root: StateRoot
    slot_number: SlotNumber
    block_hash: BlockHash
    block_number: BlockNumber
    block_timestamp: Timestamp


@dataclass(frozen=True)
class ReferenceBlockStamp(BlockStamp):
    # Ref slot could differ from slot_number if ref_slot was missed slot_number will be previous first non-missed slot
    ref_slot: SlotNumber
    ref_epoch: EpochNumber
