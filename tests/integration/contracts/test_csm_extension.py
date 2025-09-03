from unittest.mock import Mock

import pytest

from src.web3py.extensions.csm import CSM
from src.web3py.types import Web3


@pytest.fixture
def w3(web3_provider_integration):
    web3_provider_integration.attach_modules({"csm": CSM})
    return web3_provider_integration


@pytest.mark.integration
@pytest.mark.skip("CSM v2 is not yet live")
def test_csm_extension(w3: Web3):
    w3.csm.get_csm_last_processing_ref_slot(Mock(block_hash="latest"))
    w3.csm.get_rewards_tree_root(Mock(block_hash="latest"))
    w3.csm.get_rewards_tree_cid(Mock(block_hash="latest"))
    w3.csm.get_curve_params(Mock(0), Mock(block_hash="latest"))
    w3.csm.get_strikes_tree_root(Mock(block_hash="latest"))
    w3.csm.get_strikes_tree_cid(Mock(block_hash="latest"))
