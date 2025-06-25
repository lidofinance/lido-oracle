import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field

from src.modules.csm.state import DutyAccumulator
from src.modules.csm.types import RewardsShares
from src.providers.execution.contracts.cs_parameters_registry import PerformanceCoefficients
from src.types import EpochNumber, NodeOperatorId, ReferenceBlockStamp, ValidatorIndex


class LogJSONEncoder(json.JSONEncoder): ...


@dataclass
class ValidatorFrameSummary:
    distributed_rewards: RewardsShares = 0
    performance: float = 0.0
    threshold: float = 0.0
    rewards_share: float = 0.0
    slashed: bool = False
    strikes: int = 0
    attestation_duty: DutyAccumulator = field(default_factory=DutyAccumulator)
    proposal_duty: DutyAccumulator = field(default_factory=DutyAccumulator)
    sync_duty: DutyAccumulator = field(default_factory=DutyAccumulator)


@dataclass
class OperatorFrameSummary:
    distributed_rewards: RewardsShares = 0
    performance_coefficients: PerformanceCoefficients = field(default_factory=PerformanceCoefficients)
    validators: dict[ValidatorIndex, ValidatorFrameSummary] = field(default_factory=lambda: defaultdict(ValidatorFrameSummary))


@dataclass
class FramePerfLog:
    """A log of performance assessed per operator in the given frame"""
    blockstamp: ReferenceBlockStamp
    frame: tuple[EpochNumber, EpochNumber]
    distributable: RewardsShares = 0
    distributed_rewards: RewardsShares = 0
    rebate_to_protocol: RewardsShares = 0
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
