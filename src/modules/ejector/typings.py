from dataclasses import dataclass

from src.typings import SlotNumber


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
    consensusVersion: int
    ref_slot: SlotNumber
    requests_count: int
    data_format: int
    data: bytes

    def as_tuple(self):
        # Tuple with report in correct order
        return (
            self.consensusVersion,
            self.ref_slot,
            self.requests_count,
            self.data_format,
            self.data,
        )
