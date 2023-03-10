import pytest

from tests.factory.base import ReferenceBlockStampFactory


blockstamp = ReferenceBlockStampFactory.build(
    state_root='0x623801c28526c1923f14e1bb5258e40a194059c42e280ee61c7189bf2fdbe05e'
)


@pytest.mark.unit
def test_get_lido_validators(web3, lido_validators):
    validators_in_cc = web3.cc.get_validators(blockstamp)

    lido_keys = web3.kac.get_all_lido_keys(blockstamp)

    lido_validators = web3.lido_validators.get_lido_validators(blockstamp)

    assert len(lido_validators) == 5
    assert len(lido_keys) != len(lido_validators)
    assert len(validators_in_cc) != len(lido_validators)

    for v in lido_validators:
        assert v.lido_id.key == v.validator.pubkey


@pytest.mark.unit
def test_get_node_operators(web3, lido_validators, contracts):
    node_operators = web3.lido_validators.get_lido_node_operators(blockstamp)

    assert len(node_operators) == 2

    registry_map = {
        0: '0x8a1E2986E52b441058325c315f83C9D4129bDF72',
        1: '0x8a1E2986E52b441058325c315f83C9D4129bDF72',
    }

    for no in node_operators:
        assert no.staking_module.staking_module_address == registry_map[no.id]


@pytest.mark.unit
def test_get_lido_validators_by_node_operator(web3, lido_validators, contracts):
    no_validators = web3.lido_validators.get_lido_validators_by_node_operators(blockstamp)

    assert len(no_validators.keys()) == 2
    assert len(no_validators[(1, 0)]) == 5
    assert len(no_validators[(1, 1)]) == 0
