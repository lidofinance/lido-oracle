from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

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


@dataclass(frozen=True)
class BlockStamp:
    ref_slot_number: SlotNumber
    ref_epoch: EpochNumber
    block_root: BlockRoot
    state_root: StateRoot
    slot_number: SlotNumber
    block_hash: BlockHash
    block_number: BlockNumber


@dataclass()
class OracleReportLimits:
    churnValidatorsPerDayLimit: int
    oneOffCLBalanceDecreaseBPLimit: int
    annualBalanceIncreaseBPLimit: int
    shareRateDeviationBPLimit: int
    requestTimestampMargin: int
    maxPositiveTokenRebase: int
    maxValidatorExitRequestsPerReport: int
    maxAccountingExtraDataListItemsCount: int
