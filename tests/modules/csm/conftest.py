import pytest

from web3py.extensions.staking_module import StakingModuleContracts


@pytest.fixture()
def web3(web3):
    web3.attach_modules(
        {
            "staking_module": StakingModuleContracts,
        }
    )
    yield web3
