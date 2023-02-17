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

Gwei = NewType('Gwei', int)


@dataclass(frozen=True)
class BlockStamp:
    block_root: BlockRoot
    state_root: StateRoot
    slot_number: SlotNumber
    block_hash: BlockHash
    block_number: BlockNumber


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
