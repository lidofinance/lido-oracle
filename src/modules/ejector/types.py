from dataclasses import dataclass

from src.types import SlotNumber


@dataclass
class EjectorProcessingState:
    current_frame_ref_slot: SlotNumber
    processing_deadline_time: int
    data_hash: bytes
    data_submitted: bool
    data_format: int
    requests_count: int
    requests_submitted: int


@dataclass
class ReportData:
    consensus_version: int
    ref_slot: SlotNumber
    requests_count: int
    data_format: int
    data: bytes
