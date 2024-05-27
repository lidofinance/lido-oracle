import pytest

from src.modules.accounting.types import LidoReportRebase
from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.integration
def test_deposit_security_module_call(lido_contract, accounting_oracle_contract, burner_contract, caplog):
    check_contract(
        lido_contract,
        [
            (
                'handle_oracle_report',
                (
                    1716724811,  # timestamp
                    86400,
                    346727,
                    9290022163214746000000000,
                    898180576095000000000,
                    105274292338382770653,
                    0,
                    accounting_oracle_contract.address,
                    # '0xb35dd0cae381072a4856c08cf06013e56998d9152e970d89a1f38e92f133a8ea',
                ),
                lambda response: check_value_type(response, LidoReportRebase),
            ),
            ('get_buffered_ether', None, lambda response: check_value_type(response, int)),
            ('total_supply', None, lambda response: check_value_type(response, int)),
        ],
        caplog,
    )
