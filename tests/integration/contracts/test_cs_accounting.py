import pytest
from eth_typing import ChecksumAddress

from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.integration
def test_cs_accounting(cs_accounting_contract, caplog):
    check_contract(
        cs_accounting_contract,
        [
            ("fee_distributor", None, check_is_instance_of(ChecksumAddress)),
            ("get_bond_curve_id", (0,), check_is_instance_of(int)),
        ],
        caplog,
    )
