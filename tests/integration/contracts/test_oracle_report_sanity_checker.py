import pytest

from src.modules.accounting.types import OracleReportLimits
from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.testnet
@pytest.mark.integration
def test_oracle_report_sanity_checker(oracle_report_sanity_checker_contract, caplog):
    check_contract(
        oracle_report_sanity_checker_contract,
        [
            ('get_oracle_report_limits', None, check_is_instance_of(OracleReportLimits)),
        ],
        caplog,
    )
