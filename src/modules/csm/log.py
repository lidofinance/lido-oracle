import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Callable

from src.modules.csm.state import AttestationsAccumulator
from src.types import EpochNumber, NodeOperatorId


class LogJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, AttestationsAccumulator):
            return asdict(o)
        return super().default(o)


def dictfield[K, V](typ: Callable[[], V]):
    return field(default_factory=lambda: defaultdict[K, V](typ))


@dataclass
class Validator:
    perf: AttestationsAccumulator = field(default_factory=AttestationsAccumulator)
    slashed: bool = False


@dataclass
class OperatorInfo:
    validators: dict[str, Validator] = dictfield(Validator)
    stuck: bool = False


@dataclass
class Log:
    frame: tuple[EpochNumber, EpochNumber]
    threshold: float = 0.0
    operators: dict[NodeOperatorId, OperatorInfo] = dictfield(OperatorInfo)

    def encode(self) -> bytes:
        return (
            LogJSONEncoder(
                indent=None,
                separators=(',', ':'),
                sort_keys=True,
            )
            .encode(asdict(self))
            .encode()
        )
