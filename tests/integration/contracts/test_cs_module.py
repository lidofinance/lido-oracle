import pytest
from eth_typing import ChecksumAddress

from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.integration
def test_cs_module(cs_module_contract, caplog):
    check_contract(
        cs_module_contract,
        [
            # ("parameters_registry", None, check_is_address),
            ("accounting", None, check_is_instance_of(ChecksumAddress)),
            ("is_paused", None, check_is_instance_of(bool)),
        ],
        caplog,
    )
