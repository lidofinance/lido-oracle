from unittest.mock import Mock

import pytest

from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.no_registry import ValidatorFactory, LidoKeyFactory

blockstamp = ReferenceBlockStampFactory.build()


@pytest.mark.unit
def test_get_lido_validators(web3, lido_validators):
    validators = ValidatorFactory.batch(30)
    lido_keys = LidoKeyFactory.generate_for_validators(validators[:10])
    lido_keys.extend(LidoKeyFactory.batch(5))

    web3.cc.get_validators = Mock(return_value=validators)
    web3.kac.get_all_lido_keys = Mock(return_value=lido_keys)

    lido_validators = web3.lido_validators.get_lido_validators(blockstamp)

    assert len(lido_validators) == 10
    assert len(lido_keys) != len(lido_validators)
    assert len(validators) != len(lido_validators)

    for v in lido_validators:
        assert v.lido_id.key == v.validator.pubkey


@pytest.mark.unit
def test_get_node_operators(web3, lido_validators, contracts):
    node_operators = web3.lido_validators.get_lido_node_operators(blockstamp)

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
