from unittest.mock import Mock

import pytest

from web3py.extensions.staking_module import StakingModuleContracts
from web3py.types import Web3StakingModule


@pytest.fixture
def w3(web3_provider_integration):
    web3_provider_integration.attach_modules({"staking_module": StakingModuleContracts})
    return web3_provider_integration


@pytest.mark.integration
@pytest.mark.mainnet
def test_csm_extension(w3: Web3StakingModule):
    w3.staking_module.get_last_processing_ref_slot(Mock(block_hash="latest"))
    w3.staking_module.get_rewards_tree_root(Mock(block_hash="latest"))
    w3.staking_module.get_rewards_tree_cid(Mock(block_hash="latest"))
    w3.staking_module.get_curve_params(0, Mock(block_hash="latest"))
    w3.staking_module.get_strikes_tree_root(Mock(block_hash="latest"))
    w3.staking_module.get_strikes_tree_cid(Mock(block_hash="latest"))
