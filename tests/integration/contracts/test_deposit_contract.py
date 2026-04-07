import pytest

from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.mainnet
@pytest.mark.integration
def test_deposit_contract(deposit_contract, caplog):
    check_contract(
        deposit_contract,
        [
            ('get_deposit_count', ('latest',), lambda r: check_value_type(r, int)),
        ],
        caplog,
    )
