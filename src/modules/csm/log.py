import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field

from src.modules.csm.types import Shares
from src.types import EpochNumber, NodeOperatorId, ReferenceBlockStamp


class LogJSONEncoder(json.JSONEncoder): ...


@dataclass
class AttestationsAccumulatorLog:
    assigned: int = 0
    included: int = 0


@dataclass
class ValidatorFrameSummary:
    # TODO: Should be renamed. Perf means different things in different contexts
    perf: AttestationsAccumulatorLog = field(default_factory=AttestationsAccumulatorLog)
    slashed: bool = False


@dataclass
class OperatorFrameSummary:
    distributed: int = 0
    validators: dict[str, ValidatorFrameSummary] = field(default_factory=lambda: defaultdict(ValidatorFrameSummary))
    stuck: bool = False


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
