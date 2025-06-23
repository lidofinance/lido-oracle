import pytest
from web3.contract.contract import ContractFunction

from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.integration
def test_node_operator_registry(node_operator_registry_contract, caplog):
    check_contract(
        node_operator_registry_contract,
        [
            ('get_type', None, bytes),
            ('distribute_reward', None, lambda tx: check_value_type(tx, ContractFunction)),
        ],
        caplog,
    )
