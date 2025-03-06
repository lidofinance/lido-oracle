import pytest
from hexbytes import HexBytes

from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.integration
@pytest.mark.skip("Requires CSMv2 activated on mainnet")  # TODO: Remove the mark with CSM v2 live on mainnet
def test_cs_strikes(cs_module_contract, caplog):
    check_contract(
        cs_module_contract,
        [
            ("tree_root", None, check_is_instance_of(HexBytes)),
            ("tree_cid", None, check_is_instance_of(str)),
        ],
        caplog,
    )
