import pytest

from src.modules.accounting.types import ReportValues, CalculatedReportResults
from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.integration
def test_accounting_contract_call(accounting_contract, accounting_oracle_contract, burner_contract, caplog):
    report = ReportValues(
        timestamp=1733914164,
        time_elapsed=86400,
        cl_validators=0,
        cl_balance=0,
        withdrawal_vault_balance=0,
        el_rewards_vault_balance=0,
        shares_requested_to_burn=0,
        withdrawal_finalization_batches=[],
        vault_values=[],
        net_cash_flows=[]
    )

    check_contract(
        accounting_contract,
        [
            ('handle_oracle_report', (report, accounting_oracle_contract.address),
             lambda response: check_value_type(response, list),),
            ('simulate_oracle_report', (report, 0),
             lambda response: check_value_type(response, CalculatedReportResults),)
        ],
        caplog,
    )
