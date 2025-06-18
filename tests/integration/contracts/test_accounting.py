import pytest

from src.modules.accounting.types import ReportValues, ReportResults
from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.testnet  # TODO: Bounded to hoodie due to st. vaults task, move to mainnet after release
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
                        cl_validators=100,
                        cl_balance=0,
                        withdrawal_vault_balance=0,
                        el_rewards_vault_balance=0,
                        shares_requested_to_burn=0,
                        withdrawal_finalization_batches=[],
                        vaults_total_treasury_fees_shares=0,
                        vaults_data_tree_root=b'\x00' * 32,
                        vaults_data_tree_cid="tree_cid",
                    ),
                ),
                lambda response: check_value_type(response, ReportResults),
            ),
        ],
        caplog,
    )
