import pytest
from eth_typing import ChecksumAddress

from tests.integration.contracts.contract_utils import check_contract, make_checker


@pytest.mark.integration
def test_cs_accounting(cs_accounting_contract, caplog):
    check_contract(
        cs_accounting_contract,
        [
            ("fee_distributor", None, make_checker(ChecksumAddress)),
            ("get_bond_curve_id", (0,), make_checker(int)),
        ],
        caplog,
    )
