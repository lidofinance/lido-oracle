import pytest

from src.modules.accounting.types import ReportValues, ReportResults
from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.integration
def test_accounting_contract_call(accounting_contract, caplog):
    check_contract(
        accounting_contract,
        [
            (
                'simulate_oracle_report',
                (
                    ReportValues(
                        timestamp=0,
                        time_elapsed=0,
                        cl_validators=0,
                        cl_balance=0,
                        withdrawal_vault_balance=0,
                        el_rewards_vault_balance=0,
                        shares_requested_to_burn=0,
                        withdrawal_finalization_batches=[],
                        vaults_values=[],
                        vaults_in_out_deltas=[],
                    ),
                ),
                lambda response: check_value_type(response, ReportResults),
            ),
        ],
        caplog,
    )
