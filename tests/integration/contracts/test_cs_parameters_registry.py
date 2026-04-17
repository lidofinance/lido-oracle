import pytest

from providers.execution.contracts.cs_parameters_registry import (
    KeyNumberValueIntervalList,
    PerformanceCoefficients,
    StrikesParams,
)
from tests.integration.contracts.contract_utils import (
    check_contract,
    make_checker,
)


@pytest.mark.integration
def test_cs_parameters_registry(cs_params_contract, caplog):
    check_contract(
        cs_params_contract,
        [
            ("get_performance_coefficients", [1], make_checker(PerformanceCoefficients)),
            ("get_reward_share_data", [1], make_checker(KeyNumberValueIntervalList)),
            ("get_performance_leeway_data", [1], make_checker(KeyNumberValueIntervalList)),
            ("get_strikes_params", [1], make_checker(StrikesParams)),
        ],
        caplog,
    )
