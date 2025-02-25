import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field

from src.modules.csm.state import AttestationsAccumulator
from src.modules.csm.types import Shares
from src.types import EpochNumber, NodeOperatorId, ReferenceBlockStamp, ValidatorIndex


class LogJSONEncoder(json.JSONEncoder): ...


@dataclass
class ValidatorFrameSummary:
    attestation_duty: AttestationsAccumulator = field(default_factory=AttestationsAccumulator)
    slashed: bool = False


@dataclass
class OperatorFrameSummary:
    distributed: int = 0
    validators: dict[ValidatorIndex, ValidatorFrameSummary] = field(default_factory=lambda: defaultdict(ValidatorFrameSummary))


@dataclass
class FramePerfLog:
    """A log of performance assessed per operator in the given frame"""

    blockstamp: ReferenceBlockStamp
    frame: tuple[EpochNumber, EpochNumber]
    threshold: float = 0.0
    distributable: Shares = 0
    operators: dict[NodeOperatorId, OperatorFrameSummary] = field(
        default_factory=lambda: defaultdict(OperatorFrameSummary)
    )

    @staticmethod
    def encode(logs: list['FramePerfLog']) -> bytes:
        return (
            LogJSONEncoder(
                indent=None,
                separators=(',', ':'),
                sort_keys=True,
            )
            .encode([asdict(log) for log in logs])
            .encode()
        )
