import pytest
from hexbytes import HexBytes
from web3.exceptions import ContractLogicError

from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.integration
@pytest.mark.xfail(raises=ContractLogicError, reason="CSMv2 is not yet live")
def test_cs_strikes(cs_strikes_contract, caplog):
    check_contract(
        cs_strikes_contract,
        [
            ("tree_root", None, check_is_instance_of(HexBytes)),
            ("tree_cid", None, check_is_instance_of(str)),
        ],
        caplog,
    )
