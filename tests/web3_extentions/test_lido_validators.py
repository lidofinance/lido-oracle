import pytest


@pytest.mark.unit
def test_get_lido_validators(web3, lido_validators, past_blockstamp):
    validators_in_cc = web3.cc.get_validators(past_blockstamp.state_root)

    lido_keys = web3.kac.get_all_lido_keys(past_blockstamp)

    lido_validators = web3.lido_validators.get_lido_validators(past_blockstamp)

    assert len(lido_validators) == 3
    assert len(lido_keys) != len(lido_validators)
    assert len(validators_in_cc) != len(lido_validators)

    for validator in lido_validators:
        assert validator.key.key == validator.validator.validator.pubkey


@pytest.mark.unit
def test_get_node_operators(web3, lido_validators, contracts, past_blockstamp):
    node_operators = web3.lido_validators.get_lido_node_operators(past_blockstamp)

    assert len(node_operators) == 3

    registry_map = {
        'F4ever': '0x1D4AF1Ee19Dad8857db3a45B0374c81c8A1C6320',
        'Doom': '0x9D4AF1Ee19Dad8857db3a45B0374c81c8A1C6320',
        'Guy': '0x9D4AF1Ee19Dad8857db3a45B0374c81c8A1C6320'
    }

    for no in node_operators:
        assert no.stakingModuleAddress == registry_map[no.id]


@pytest.mark.unit
def test_get_lido_validators_by_node_operator(web3, lido_validators, past_blockstamp):
    no_validators = web3.lido_validators.get_lido_validators_by_node_operators(past_blockstamp)

    assert len(no_validators.keys()) == 3
    assert len(no_validators[('0x9D4AF1Ee19Dad8857db3a45B0374c81c8A1C6320', 0)]) == 2
    assert len(no_validators[('0x1D4AF1Ee19Dad8857db3a45B0374c81c8A1C6320', 0)]) == 0
