import pytest
from hexbytes import HexBytes

from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.integration
def test_cs_strikes(cs_strikes_contract, caplog):
    check_contract(
        cs_strikes_contract,
        [
            ("tree_root", None, check_is_instance_of(HexBytes)),
            ("tree_cid", None, check_is_instance_of(str)),
        ],
        caplog,
    )
