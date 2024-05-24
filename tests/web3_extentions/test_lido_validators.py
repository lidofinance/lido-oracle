from unittest.mock import Mock

import pytest

from src.web3py.extensions.lido_validators import CountOfKeysDiffersException
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.no_registry import (
    LidoKeyFactory,
    LidoValidatorFactory,
    NodeOperatorFactory,
    StakingModuleFactory,
    ValidatorFactory,
)


blockstamp = ReferenceBlockStampFactory.build()


@pytest.mark.unit
def test_get_lido_validators(web3, lido_validators, contracts):
    validators = ValidatorFactory.batch(30)
    lido_keys = LidoKeyFactory.generate_for_validators(validators[:10])
    lido_keys.extend(LidoKeyFactory.batch(10))

    web3.cc.get_validators = Mock(return_value=validators)
    web3.kac.get_used_lido_keys = Mock(return_value=lido_keys)

    lido_validators = web3.lido_validators.get_lido_validators(blockstamp)

    assert len(lido_validators) == 10
    assert len(lido_keys) != len(lido_validators)
    assert len(validators) != len(lido_validators)

    for v in lido_validators:
        assert v.lido_id.key == v.validator.pubkey


@pytest.mark.unit
def test_kapi_has_lesser_keys_than_deposited_validators_count(web3, lido_validators, contracts):
    validators = ValidatorFactory.batch(10)
    lido_keys = []

    web3.cc.get_validators = Mock(return_value=validators)
    web3.kac.get_used_lido_keys = Mock(return_value=lido_keys)

    with pytest.raises(CountOfKeysDiffersException):
        web3.lido_validators.get_lido_validators(blockstamp)


@pytest.mark.unit
def test_get_node_operators(web3, lido_validators, contracts):
    node_operators = web3.lido_contracts.staking_router.get_lido_node_operator_digests(blockstamp.block_hash)

    assert len(node_operators) == 2

    registry_map = {
        0: '0xB099EC462e42Ac2570fB298B42083D7A499045D8',
        1: '0xB099EC462e42Ac2570fB298B42083D7A499045D8',
    }

    for no in node_operators:
        assert no.staking_module.staking_module_address == registry_map[no.id]


@pytest.mark.unit
def test_get_lido_validators_by_node_operator(web3, lido_validators, contracts):
    no_validators = web3.lido_validators.get_lido_validators_by_node_operators(blockstamp)

    assert len(no_validators.keys()) == 2
    assert len(no_validators[(1, 0)]) == 10
    assert len(no_validators[(1, 1)]) == 7


@pytest.mark.unit
@pytest.mark.usefixtures('lido_validators', 'contracts')
def test_get_lido_validators_by_node_operator_inconsistent(web3, caplog):
    validator = LidoValidatorFactory.build()
    web3.lido_validators.get_lido_validators = Mock(return_value=[validator])
    web3.lido_contracts.staking_router.get_lido_node_operator_digests = Mock(
        return_value=[
            NodeOperatorFactory.build(
                staking_module=StakingModuleFactory.build(
                    staking_module_address=validator.lido_id.moduleAddress,
                ),
            ),
        ]
    )

    web3.lido_validators.get_lido_validators_by_node_operators(blockstamp)
    assert "not exist in staking router" in caplog.text
