from pydantic import BaseModel

from src.types import ValidatorIndex


class ProposalDuty(BaseModel):
    validator_index: int
    is_proposed: bool


class SyncDuty(BaseModel):
    validator_index: int
    missed_count: int  # 0..32


type AttDutyMisses = set[ValidatorIndex]
