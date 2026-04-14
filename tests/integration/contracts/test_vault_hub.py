import pytest

from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.testnet
@pytest.mark.integration
def test_vault_hub_contract(vault_hub_contract, caplog):
    check_contract(
        vault_hub_contract,
        [
            ('get_minted_events', (0, 100), lambda r: check_value_type(r, list)),
            ('get_burned_events', (0, 100), lambda r: check_value_type(r, list)),
            ('get_vault_fee_updated_events', (0, 100), lambda r: check_value_type(r, list)),
            ('get_vault_rebalanced_events', (0, 100), lambda r: check_value_type(r, list)),
            ('get_bad_debt_socialized_events', (0, 100), lambda r: check_value_type(r, list)),
            ('get_bad_debt_written_off_to_be_internalized_events', (0, 100), lambda r: check_value_type(r, list)),
            ('get_vault_connected_events', (0, 100), lambda r: check_value_type(r, list)),
        ],
        caplog,
    )
