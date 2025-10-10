import pytest

from src.modules.accounting.types import OnChainIpfsVaultReportData
from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.mainnet
@pytest.mark.integration
def test_lazy_oracle_contract_call(lazy_oracle_contract, caplog):
    check_contract(
        lazy_oracle_contract,
        [
            ('get_vaults_count', None, lambda response: check_value_type(response, int)),
            ('get_latest_report_data', None, lambda response: check_value_type(response, OnChainIpfsVaultReportData)),
            ('get_vaults', (0, 10), lambda response: check_value_type(response, list)),
            (
                'get_validator_stages',
                (
                    [
                        "0x862d53d9e4313374d202f2b28e6ffe64efb0312f9c2663f2eef67b72345faa8932b27f9b9bb7b476d9b5e418fea99124",
                        "0xa5d9411ef615c74c9240634905d5ddd46dc40a87a09e8cc0332afddb246d291303e452a850917eefe09b3b8c70a307ce",
                    ],
                    5,
                ),
                lambda response: check_value_type(response, dict),
            ),
        ],
        caplog,
    )
