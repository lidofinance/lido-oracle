import pytest
from web3.types import Wei

from src.modules.accounting.types import (
    ReportSimulationPayload,
    ReportSimulationResults,
)
from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.testnet
@pytest.mark.integration
@pytest.mark.skip("Some real numbers required for simulation to pass")
def test_accounting_contract_call(accounting_contract, caplog):
    check_contract(
        accounting_contract,
        [
            (
                'simulate_oracle_report',
                (
                    ReportSimulationPayload(
                        timestamp=0,
                        time_elapsed=0,
                        cl_validators=100,
                        cl_balance=Wei(0),
                        withdrawal_vault_balance=Wei(0),
                        el_rewards_vault_balance=Wei(0),
                        shares_requested_to_burn=0,
                        withdrawal_finalization_batches=[],
                        simulated_share_rate=0,
                    ),
                ),
                lambda response: check_value_type(response, ReportSimulationResults),
            ),
        ],
        caplog,
    )
