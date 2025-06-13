import pytest
from eth_typing import ChecksumAddress
from web3.exceptions import ContractLogicError

from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.integration
@pytest.mark.mainnet
def test_cs_module(cs_module_contract, caplog):
    check_contract(
        cs_module_contract,
        [
            ("accounting", None, check_is_instance_of(ChecksumAddress)),
            ("is_paused", None, check_is_instance_of(bool)),
        ],
        caplog,
    )


@pytest.mark.integration
@pytest.mark.mainnet
@pytest.mark.xfail(raises=ContractLogicError, reason="CSMv2 is not yet live")
def test_cs_module_v2(cs_module_contract, caplog):
    check_contract(
        cs_module_contract,
        [
            ("parameters_registry", None, check_is_instance_of(ChecksumAddress)),
        ],
        caplog,
    )
