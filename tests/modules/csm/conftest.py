import pytest

from unittest.mock import patch

from src import variables
from src.web3py.extensions.staking_module import StakingModuleContracts


@pytest.fixture()
def web3(web3):
    with patch.object(variables, 'CURATED_MODULE_ADDRESS', None):
        web3.attach_modules(
            {
                "staking_module": StakingModuleContracts,
            }
        )
        yield web3
