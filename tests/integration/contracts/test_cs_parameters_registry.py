import pytest
from web3.exceptions import ContractLogicError

from src.providers.execution.contracts.cs_parameters_registry import (
    PerformanceCoefficients,
    KeyNumberValueIntervalList,
    StrikesParams,
)
from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.integration
@pytest.mark.xfail(raises=ContractLogicError, reason="CSMv2 is not yet live")
def test_cs_parameters_registry(cs_params_contract, caplog):
    check_contract(
        cs_params_contract,
        [
            ("get_performance_coefficients", None, check_is_instance_of(PerformanceCoefficients)),
            ("get_reward_share_data", None, check_is_instance_of(KeyNumberValueIntervalList)),
            ("get_performance_leeway_data", None, check_is_instance_of(KeyNumberValueIntervalList)),
            ("get_strikes_params", None, check_is_instance_of(StrikesParams)),
        ],
        caplog,
    )
