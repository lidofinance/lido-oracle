import pytest

from src.web3py.extensions.lido_validators import StakingModule, NodeOperator
from tests.factory.no_registry import StakingModuleFactory
from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.mainnet
@pytest.mark.integration
def test_staking_router(staking_router_contract, caplog):
    check_contract(
        staking_router_contract,
        [
            (
                'get_staking_modules',
                None,
                lambda response: check_value_type(response, list)
                and map(lambda sm: check_value_type(sm, StakingModule), response),
            ),
            (
                'get_all_node_operator_digests',
                (StakingModuleFactory.build(id=1),),
                lambda response: check_value_type(response, list)
                and map(lambda sm: check_value_type(sm, NodeOperator), response),
            ),
            ('get_contract_version', None, lambda response: check_value_type(response, int)),
        ],
        caplog,
    )
