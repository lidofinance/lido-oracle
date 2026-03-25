import pytest

from src.modules.oracles.accounting.types import OracleReportLimits
from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.testnet
@pytest.mark.integration
@pytest.mark.skip(reason="Uncomment on SRv3 Hoodi release")
def test_oracle_report_sanity_checker(oracle_report_sanity_checker_contract, caplog):
    check_contract(
        oracle_report_sanity_checker_contract,
        [
            ('get_oracle_report_limits', None, check_is_instance_of(OracleReportLimits)),
        ],
        caplog,
    )
