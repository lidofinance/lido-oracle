import pytest

from src.providers.execution.contracts.cs_parameters_registry import (
    PerformanceCoefficients,
    PerformanceLeeway,
    RewardShare,
    StrikesParams,
)
from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.integration
@pytest.mark.skip("Requires CSMv2 activated on mainnet")  # TODO: Remove the mark with CSM v2 live on mainnet
def test_cs_parameters_registry(cs_params_contract, caplog):
    check_contract(
        cs_params_contract,
        [
            ("get_performance_coefficients", None, check_is_instance_of(PerformanceCoefficients)),
            ("get_reward_share_data", None, check_is_instance_of(RewardShare)),
            ("get_performance_leeway_data", None, check_is_instance_of(PerformanceLeeway)),
            ("get_strikes_params", None, check_is_instance_of(StrikesParams)),
        ],
        caplog,
    )
