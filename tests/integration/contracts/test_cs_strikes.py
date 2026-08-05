import pytest
from hexbytes import HexBytes

from tests.integration.contracts.contract_utils import check_contract, make_checker


@pytest.mark.integration
def test_cs_strikes(cs_strikes_contract, caplog):
    check_contract(
        cs_strikes_contract,
        [
            ("tree_root", ('latest',), make_checker(HexBytes)),
            ("tree_cid", ('latest',), make_checker(str)),
        ],
        caplog,
    )
