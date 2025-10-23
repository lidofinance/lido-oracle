from dataclasses import dataclass

from src.types import SlotNumber, CommitteeIndex, BlockRoot, ValidatorIndex


@dataclass
class ValidatorDuty:
    validator_index: ValidatorIndex
    included: bool


type SlotBlockRoot = tuple[SlotNumber, BlockRoot | None]
type SyncCommittees = dict[SlotNumber, list[ValidatorDuty]]
type ProposeDuties = dict[SlotNumber, ValidatorDuty]
type AttestationCommittees = dict[tuple[SlotNumber, CommitteeIndex], list[ValidatorDuty]]
