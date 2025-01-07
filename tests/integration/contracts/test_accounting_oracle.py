import pytest
from web3.contract.contract import ContractFunction

from src.modules.accounting.types import AccountingProcessingState
from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.integration
@pytest.mark.parametrize('environment', ['holesky-vaults-devnet-2'], indirect=True)
def test_accounting_oracle_contract(accounting_oracle_contract, caplog):
    check_contract(
        accounting_oracle_contract,
        [
            ('get_processing_state', None, lambda response: check_value_type(response, AccountingProcessingState)),
            ('submit_report_extra_data_empty', None, lambda tx: check_value_type(tx, ContractFunction)),
            ('submit_report_extra_data_list', (b'',), lambda tx: check_value_type(tx, ContractFunction)),
        ],
        caplog,
    )
