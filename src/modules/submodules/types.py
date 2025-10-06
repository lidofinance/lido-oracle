from dataclasses import dataclass

from src.types import SlotNumber

ZERO_HASH = bytes([0]*32)


@dataclass
class MemberInfo:
    is_report_member: bool
    is_submit_member: bool
    is_fast_lane: bool
    last_report_ref_slot: SlotNumber
    fast_lane_length_slot: int
    current_frame_ref_slot: SlotNumber
    deadline_slot: SlotNumber
    current_frame_member_report: bytes
    current_frame_consensus_report: bytes


@dataclass(frozen=True)
class ChainConfig:
    slots_per_epoch: int
    seconds_per_slot: int
    genesis_time: int

@dataclass(frozen=True)
class ConsensusGenesisConfig:
    genesis_time: int

@dataclass(frozen=True)
class CurrentFrame:
    # Order is important!
    ref_slot: SlotNumber
    report_processing_deadline_slot: SlotNumber


@dataclass(frozen=True)
class FrameConfig:
    # Order is important!
    initial_epoch: int
    epochs_per_frame: int
    fast_lane_length_slots: int
