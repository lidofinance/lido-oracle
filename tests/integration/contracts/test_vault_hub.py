import pytest

from src.modules.accounting.types import VaultSocket
from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.integration
def test_vault_hub_contract_call(vault_hub_contract, caplog):
    check_contract(
        vault_hub_contract,
        [
            ('get_vaults_count', None, lambda response: check_value_type(response, int)),
            ('vault_socket', (0,), lambda response: check_value_type(response, VaultSocket)),
        ],
        caplog,
    )
