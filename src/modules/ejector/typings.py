from dataclasses import dataclass

from src.typings import SlotNumber


@dataclass
class ProcessingState:
    current_frame_ref_slot: SlotNumber
    processing_deadline_time: int
    data_hash: bytes
    data_submitted: bool
    data_format: int
    requests_count: int
    requests_submitted: int