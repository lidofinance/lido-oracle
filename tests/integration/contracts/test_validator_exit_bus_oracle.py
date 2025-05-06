import pytest

from src.modules.ejector.types import EjectorProcessingState
from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.mainnet
@pytest.mark.integration
def test_vebo(validators_exit_bus_oracle_contract, caplog):
    check_contract(
        validators_exit_bus_oracle_contract,
        [
            ('is_paused', None, lambda response: check_value_type(response, bool)),
            ('get_processing_state', None, lambda response: check_value_type(response, EjectorProcessingState)),
            (
                'get_last_requested_validator_indices',
                (1, [1]),
                lambda response: check_value_type(response, list) and map(lambda val: check_value_type(val, int)),
            ),
        ],
        caplog,
    )
