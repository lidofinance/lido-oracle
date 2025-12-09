import pytest

from src.modules.ejector.types import EjectorProcessingState
from tests.integration.contracts.contract_utils import (
    check_contract,
    check_is_instance_of,
)


@pytest.mark.mainnet
@pytest.mark.integration
def test_vebo(validators_exit_bus_oracle_contract, caplog):
    check_contract(
        validators_exit_bus_oracle_contract,
        [
            ('is_paused', None, check_is_instance_of(bool)),
            ('get_processing_state', None, check_is_instance_of(EjectorProcessingState)),
        ],
        caplog,
    )
