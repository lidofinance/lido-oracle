from unittest.mock import Mock

from src.constants import EFFECTIVE_BALANCE_INCREMENT, MIN_ACTIVATION_BALANCE
from src.providers.execution.contracts.cs_parameters_registry import (
    CurveParams,
    KeyNumberValueInterval,
    KeyNumberValueIntervalList,
    PerformanceCoefficients,
)
from src.types import BlockHash, NodeOperatorId, ValidatorIndex
from tests.factory.no_registry import LidoValidatorFactory


HASH_A = BlockHash("0x" + "a" * 64)
HASH_B = BlockHash("0x" + "b" * 64)
NO_ID = NodeOperatorId(7)
ASSIGNED_ATTESTATIONS = 10
FULL_SHARE = ASSIGNED_ATTESTATIONS * MIN_ACTIVATION_BALANCE // EFFECTIVE_BALANCE_INCREMENT


def make_curve_params(reward_share_intervals: list[KeyNumberValueInterval]) -> CurveParams:
    return CurveParams(
        perf_coeffs=PerformanceCoefficients(attestations_weight=1, blocks_weight=0, sync_weight=0),
        perf_leeway_data=KeyNumberValueIntervalList([KeyNumberValueInterval(1, 0)]),
        reward_share_data=KeyNumberValueIntervalList(reward_share_intervals),
        strikes_params=Mock(),
    )


def make_active_validator(index: int, balance_multiplier: int = 1):
    validator = LidoValidatorFactory.build(index=ValidatorIndex(index))
    validator.validator.slashed = False
    validator.validator.effective_balance = MIN_ACTIVATION_BALANCE * balance_multiplier
    return validator
