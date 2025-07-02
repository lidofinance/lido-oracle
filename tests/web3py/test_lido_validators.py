from unittest.mock import Mock

import pytest

from src.modules.accounting.types import BeaconStat
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
def test_get_lido_validators(web3):
    validators = ValidatorFactory.batch(30)
    lido_keys = LidoKeyFactory.generate_for_validators(validators[:10])
    lido_keys.extend(LidoKeyFactory.batch(10))

    web3.lido_validators._kapi_sanity_check = Mock()

    web3.cc.get_validators = Mock(return_value=validators)
    web3.kac.get_used_lido_keys = Mock(return_value=lido_keys)

    lido_validators = web3.lido_validators.get_lido_validators(blockstamp)

    assert len(lido_validators) == 10
    assert len(lido_keys) != len(lido_validators)
    assert len(validators) != len(lido_validators)

    for v in lido_validators:
        assert v.lido_id.key == v.validator.pubkey


@pytest.mark.unit
def test_kapi_has_lesser_keys_than_deposited_validators_count(web3):
    validators = ValidatorFactory.batch(10)
    lido_keys = [LidoKeyFactory.build()]

    web3.cc.get_validators = Mock(return_value=validators)
    web3.kac.get_used_lido_keys = Mock(return_value=lido_keys)
    web3.lido_contracts.lido.get_beacon_stat = Mock(
        return_value=BeaconStat(
            deposited_validators=10,
            beacon_validators=0,
            beacon_balance=0,
        )
    )

    with pytest.raises(CountOfKeysDiffersException):
        web3.lido_validators.get_lido_validators(blockstamp)

    web3.lido_contracts.lido.get_beacon_stat = Mock(
        return_value=BeaconStat(
            deposited_validators=1,
            beacon_validators=0,
            beacon_balance=0,
        )
    )

    web3.lido_validators.get_lido_validators(blockstamp)

    # Keys can exist in KAPI, but no yet represented on CL
    web3.lido_contracts.lido.get_beacon_stat = Mock(
        return_value=BeaconStat(
            deposited_validators=0,
            beacon_validators=0,
            beacon_balance=0,
        )
    )

    web3.lido_validators.get_lido_validators(blockstamp)


@pytest.mark.unit
def test_get_lido_node_operators_by_modules(web3):
    web3.lido_contracts.staking_router.get_staking_modules = Mock(
        return_value=[
            StakingModuleFactory.build(id=1),
            StakingModuleFactory.build(id=2),
        ]
    )
    web3.lido_contracts.staking_router.get_all_node_operator_digests = Mock(side_effect=lambda x, _: list(range(x.id)))

    result = web3.lido_validators.get_lido_node_operators_by_modules(blockstamp)

    for key, value in result.items():
        assert len(value) == key


@pytest.mark.unit
def test_get_node_operators(web3):
    web3.lido_validators.get_lido_node_operators_by_modules = Mock(
        return_value={
            0: [0, 2, 3],
            1: [1, 5],
        }
    )

    node_operators = web3.lido_validators.get_lido_node_operators(blockstamp)

    assert len(node_operators) == 5


@pytest.mark.unit
def test_get_lido_validators_by_node_operator(web3):
    # 2 NO in one module
    # 1 NO in 2 module
    sm1 = StakingModuleFactory.build(id=1)
    sm2 = StakingModuleFactory.build(id=2)

    web3.lido_validators.get_lido_validators = Mock(
        return_value=[
            LidoValidatorFactory.build(
                lido_id=LidoKeyFactory.build(
                    operatorIndex=1,
                    moduleAddress=sm1.staking_module_address,
                )
            ),
            LidoValidatorFactory.build(
                lido_id=LidoKeyFactory.build(
                    operatorIndex=1,
                    moduleAddress=sm1.staking_module_address,
                )
            ),
            LidoValidatorFactory.build(
                lido_id=LidoKeyFactory.build(
                    operatorIndex=1,
                    moduleAddress=sm2.staking_module_address,
                )
            ),
        ]
    )
    web3.lido_validators.get_lido_node_operators = Mock(
        return_value=[
            NodeOperatorFactory.build(
                id=1,
                staking_module=sm1,
            ),
            NodeOperatorFactory.build(
                id=2,
                staking_module=sm1,
            ),
            NodeOperatorFactory.build(
                id=1,
                staking_module=sm2,
            ),
        ]
    )

    no_validators = web3.lido_validators.get_lido_validators_by_node_operators(blockstamp)

    assert len(no_validators.keys()) == 3
    assert len(no_validators[(1, 1)]) == 2
    assert len(no_validators[(2, 1)]) == 1


@pytest.mark.unit
def test_get_lido_validators_by_node_operator_inconsistent(web3, caplog):
    validator = LidoValidatorFactory.build()
    web3.lido_validators.get_lido_validators = Mock(return_value=[validator])
    web3.lido_validators.get_lido_node_operators = Mock(
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
