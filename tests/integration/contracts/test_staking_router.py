import logging

import pytest

from src.web3py.extensions.lido_validators import StakingModule, NodeOperator
from tests.factory.no_registry import StakingModuleFactory
from tests.integration.contracts.contract_utils import check_contract, check_value_type


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
        ],
        caplog,
    )


@pytest.mark.integration
def test_staking_router_v2(staking_router_contract_v2, caplog):
    check_contract(
        staking_router_contract_v2,
        [
            (
                'get_all_node_operator_digests',
                (StakingModuleFactory.build(id=1),),
                lambda response: check_value_type(response, list)
                and map(lambda sm: check_value_type(sm, NodeOperator), response),
            ),
        ],
        caplog,
    )


@pytest.mark.integration
def test_backward_compitability_staking_router_v2(staking_router_contract_v2, caplog):
    caplog.set_level(logging.DEBUG)

    # Block with old staking router
    staking_modules = staking_router_contract_v2.get_staking_modules(20929216)

    assert "{'msg': 'Use StakingRouterV1.json abi (old one) to parse the response.'}" in caplog.messages

    log_with_call = list(filter(lambda log: 'Call ' in log or 'Build ' in log, caplog.messages))

    assert 'Call `getContractVersion()`' in log_with_call[0]
    assert 'Call `getStakingModules()`' in log_with_call[1]

    assert len(staking_modules)
