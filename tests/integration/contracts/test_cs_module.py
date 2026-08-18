import pytest
from eth_typing import ChecksumAddress

from tests.integration.contracts.contract_utils import check_contract, make_checker


@pytest.mark.integration
@pytest.mark.mainnet
def test_cs_module(cs_module_contract, caplog):
    check_contract(
        cs_module_contract,
        [
            ("accounting", ('latest',), make_checker(ChecksumAddress)),
            ("is_paused", ('latest',), make_checker(bool)),
        ],
        caplog,
    )


@pytest.mark.integration
@pytest.mark.mainnet
def test_cs_module_v2(cs_module_contract, caplog):
    check_contract(
        cs_module_contract,
        [
            ("parameters_registry", ('latest',), make_checker(ChecksumAddress)),
        ],
        caplog,
    )
