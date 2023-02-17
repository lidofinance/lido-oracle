from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

from eth_typing import HexStr
from hexbytes import HexBytes


class OracleModule(StrEnum):
    ACCOUNTING = 'accounting'
    EJECTOR = 'ejector'


EpochNumber = NewType('EpochNumber', int)

StateRoot = NewType('StateRoot', HexStr)
BlockRoot = NewType('BlockRoot', HexStr)
SlotNumber = NewType('SlotNumber', int)

BlockHash = NewType('BlockHash', HexStr)
BlockNumber = NewType('BlockNumber', int)

Gwei = NewType('Gwei', int)


@dataclass(frozen=True)
class BlockStamp:
    block_root: BlockRoot
    state_root: StateRoot
    slot_number: SlotNumber
    block_hash: BlockHash
    block_number: BlockNumber


@dataclass(frozen=True)
class RefBlockStamp(BlockStamp):
    ref_slot_number: SlotNumber  # in good weather (when slot_number is not missed) should be the same as slot_number
    ref_epoch: EpochNumber  # in good weather (when slot_number is not missed) should be the same as epoch_number


@dataclass()
class OracleReportLimits:
    churn_validators_per_day_limit: int
    one_off_cl_balance_decrease_bp_limit: int
    annual_balance_increase_bp_limit: int
    share_rate_deviation_bp_limit: int
    request_timestamp_margin: int
    max_positive_token_rebase: int
    max_validator_exit_requests_per_report: int
    max_accounting_extra_data_list_items_count: int
