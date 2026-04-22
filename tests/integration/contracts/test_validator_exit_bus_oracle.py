import pytest

from src.modules.oracles.ejector.types import EjectorProcessingState
from tests.integration.contracts.contract_utils import (
    check_contract,
    make_checker,
)


@pytest.mark.mainnet
@pytest.mark.integration
def test_vebo(validators_exit_bus_oracle_contract, caplog):
    check_contract(
        validators_exit_bus_oracle_contract,
        [
            ('is_paused', None, make_checker(bool)),
            ('get_processing_state', None, make_checker(EjectorProcessingState)),
        ],
        caplog,
    )
