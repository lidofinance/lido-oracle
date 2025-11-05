import pytest

from src.modules.accounting.types import OnChainIpfsVaultReportData
from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.testnet
@pytest.mark.integration
def test_lazy_oracle_contract_call(lazy_oracle_contract, caplog):
    check_contract(
        lazy_oracle_contract,
        [
            ('get_vaults_count', None, lambda response: check_value_type(response, int)),
            ('get_latest_report_data', None, lambda response: check_value_type(response, OnChainIpfsVaultReportData)),
            ('get_vaults', (0, 10), lambda response: check_value_type(response, list)),
            (
                'get_validator_statuses',
                (
                    [
                        "0x9089c69b6e94540ca87ee39dd7c3fbeb65b94d962a556a62c10eca7e8366904de4fa5f18093cf3ad5377d2c3a38a6c27",
                        "0xa5d9411ef615c74c9240634905d5ddd46dc40a87a09e8cc0332afddb246d291303e452a850917eefe09b3b8c70a307ce",
                    ],
                    5,
                ),
                lambda response: check_value_type(response, dict),
            ),
        ],
        caplog,
    )
