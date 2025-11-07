import pytest
from web3.contract.contract import ContractFunction

from src.modules.accounting.types import AccountingProcessingState
from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.testnet  # TODO: Bounded to hoodie due to st. vaults task, move to mainnet after release
@pytest.mark.integration
def test_accounting_oracle_contract(accounting_oracle_contract, caplog):
    check_contract(
        accounting_oracle_contract,
        [
            ('get_processing_state', None, check_is_instance_of(AccountingProcessingState)),
            ('submit_report_extra_data_empty', None, check_is_instance_of(ContractFunction)),
            ('submit_report_extra_data_list', (b'',), check_is_instance_of(ContractFunction)),
        ],
        caplog,
    )
