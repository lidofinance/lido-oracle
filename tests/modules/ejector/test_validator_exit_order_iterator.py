from unittest.mock import Mock

import pytest

from src.modules.submodules.types import ChainConfig
from src.services.exit_order_iterator import NodeOperatorStats, StakingModuleStats, ValidatorExitIterator
from src.web3py.extensions.lido_validators import NodeOperatorLimitMode
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.no_registry import LidoValidatorFactory, NodeOperatorFactory, StakingModuleFactory
from tests.factory.web3_factory import Web3DataclassFactory
from types import MethodType


class ModuleStatsFactory(Web3DataclassFactory[StakingModuleStats]): ...


class NodeOperatorStatsFactory(Web3DataclassFactory[NodeOperatorStats]):
    node_operator = NodeOperatorFactory
    module_stats = ModuleStatsFactory


@pytest.fixture
def iterator(web3):
    return ValidatorExitIterator(
        web3,
        ReferenceBlockStampFactory.build(),
        ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0),
    )


@pytest.mark.unit
def test_get_filter_non_exitable_validators(iterator):
    iterator.lvs.get_recently_requested_to_exit_validators_by_node_operator = Mock(
        return_value={
            (1, 1): [1],
            (1, 2): [-1],
        }
    )
    filt = iterator.get_can_request_exit_predicate((1, 1))
    assert not filt(LidoValidatorFactory.build(index="1"))

    filt = iterator.get_can_request_exit_predicate((1, 2))
    assert filt(LidoValidatorFactory.build(index="1"))


@pytest.mark.unit
def test_eject_validator(iterator):
    sk_1 = StakingModuleFactory.build(
        id=1,
        priority_exit_share_threshold=1 * 10000,
    )
    sk_2 = StakingModuleFactory.build(
        id=2,
        priority_exit_share_threshold=1 * 10000,
    )
    iterator.w3.lido_contracts.staking_router.get_staking_modules = Mock(
        return_value=[
            sk_1,
            sk_2,
        ]
    )

    no_1 = NodeOperatorFactory.build(
        id=1,
        staking_module=sk_1,
        total_deposited_validators=3,
        target_validators_count=1,
        is_target_limit_active=NodeOperatorLimitMode.FORCE,
    )
    no_2 = NodeOperatorFactory.build(
        id=2,
        staking_module=sk_1,
        total_deposited_validators=2,
        is_target_limit_active=NodeOperatorLimitMode.SOFT,
    )
    no_3 = NodeOperatorFactory.build(
        staking_module=sk_2,
        id=1,
        total_deposited_validators=3,
        is_target_limit_active=NodeOperatorLimitMode.FORCE,
    )

    iterator.w3.lido_validators.get_lido_node_operators = Mock(
        return_value=[
            no_1,
            no_2,
            no_3,
        ]
    )

    iterator.w3.lido_validators.get_lido_validators_by_node_operators = Mock(
        return_value={
            (1, 1): [
                LidoValidatorFactory.build_with_activation_epoch_bound(iterator.blockstamp.ref_epoch),
                LidoValidatorFactory.build_with_activation_epoch_bound(iterator.blockstamp.ref_epoch),
                LidoValidatorFactory.build_with_activation_epoch_bound(iterator.blockstamp.ref_epoch),
            ],
            (1, 2): [
                LidoValidatorFactory.build_with_activation_epoch_bound(iterator.blockstamp.ref_epoch),
                LidoValidatorFactory.build_with_activation_epoch_bound(iterator.blockstamp.ref_epoch),
            ],
            (2, 1): [
                LidoValidatorFactory.build_with_activation_epoch_bound(iterator.blockstamp.ref_epoch, index='8'),
                LidoValidatorFactory.build_with_activation_epoch_bound(iterator.blockstamp.ref_epoch, index='7'),
                LidoValidatorFactory.build_with_activation_epoch_bound(iterator.blockstamp.ref_epoch, index='6'),
            ],
        }
    )

    iterator.lvs.get_recently_requested_to_exit_validators_by_node_operator = Mock(
        return_value={
            (1, 1): [-1],
            (1, 2): [-1],
            (2, 1): [6],
        }
    )

    iterator._prepare_data_structure()
    iterator._calculate_lido_stats()

    assert iterator.module_stats[1].predictable_validators == 5
    assert iterator.module_stats[2].predictable_validators == 2
    assert iterator.node_operators_stats[(1, 1)].predictable_validators == 3
    assert iterator.node_operators_stats[(1, 2)].soft_exit_to is not None
    assert iterator.node_operators_stats[(2, 1)].force_exit_to is not None
    assert iterator.exitable_validators[(2, 1)][0].index == 7
    assert iterator.total_lido_validators == 7

    iterator._eject_validator((1, 1))

    assert iterator.total_lido_validators == 6
    assert iterator.module_stats[1].predictable_validators == 4
    assert iterator.node_operators_stats[(1, 1)].predictable_validators == 2

    iterator.max_validators_to_exit = 3
    iterator._load_blockchain_state = Mock()

    validators_to_eject = list(iterator)
    assert len(validators_to_eject) == 3

    ejector = iter(iterator)
    val = next(ejector)
    assert validators_to_eject[0] == val

    force_list = ejector.get_remaining_forced_validators()

    assert len(force_list) == 1
    assert force_list[0][0] == (1, 1)


@pytest.mark.unit
def test_no_predicate(iterator):
    iterator.total_lido_validators = 1000

    iterator.exitable_validators = {
        (1, 1): [LidoValidatorFactory.build(index=10)],
        (2, 2): [LidoValidatorFactory.build(index=20)],
    }

    node_operator_1 = NodeOperatorStatsFactory.build(
        predictable_validators=100,
        force_exit_to=50,
        soft_exit_to=25,
        node_operator=NodeOperatorFactory.build(id=1, staking_module=StakingModuleFactory.build(id=1)),
        module_stats=ModuleStatsFactory.build(
            predictable_validators=200,
            staking_module=StakingModuleFactory.build(priority_exit_share_threshold=0.15 * 1000),
        ),
    )

    node_operator_2 = NodeOperatorStatsFactory.build(
        predictable_validators=2000,
        force_exit_to=50,
        soft_exit_to=25,
        node_operator=NodeOperatorFactory.build(id=2, staking_module=StakingModuleFactory.build(id=2)),
        module_stats=ModuleStatsFactory.build(
            predictable_validators=200,
            staking_module=StakingModuleFactory.build(priority_exit_share_threshold=0.15 * 1000),
        ),
    )

    result = iterator._no_predicate(node_operator_2)
    assert result == (-1950, -1975, -185, -2000, 20)

    result = iterator._no_predicate(node_operator_1)
    assert result == (-50, -75, -185, -100, 10)


@pytest.mark.unit
def test_no_force_and_soft_predicate(iterator):
    nos = [
        NodeOperatorStatsFactory.build(force_exit_to=10, predictable_validators=20, soft_exit_to=20),
        NodeOperatorStatsFactory.build(force_exit_to=5, predictable_validators=5, soft_exit_to=0),
        NodeOperatorStatsFactory.build(force_exit_to=None, predictable_validators=100, soft_exit_to=20),
        NodeOperatorStatsFactory.build(force_exit_to=0, predictable_validators=4, soft_exit_to=None),
    ]

    # Priority to bigger diff exitable - forced_to
    sorted_nos = sorted(nos, key=lambda x: -iterator._no_force_predicate(x))

    assert [nos[0], nos[3], nos[1], nos[2]] == sorted_nos

    # Last two elements have same weight
    assert [
        nos[0].node_operator.id,
        nos[3].node_operator.id,
    ] == [
        no.node_operator.id for no in sorted_nos
    ][:2]

    sorted_nos = sorted(nos, key=lambda x: -iterator._no_soft_predicate(x))
    assert [
        nos[2].node_operator.id,
        nos[1].node_operator.id,
    ] == [
        no.node_operator.id for no in sorted_nos
    ][:2]


@pytest.mark.unit
def test_max_share_rate_coefficient_predicate(iterator):
    iterator.total_lido_validators = 10000

    nos = [
        NodeOperatorStatsFactory.build(
            module_stats=ModuleStatsFactory.build(
                predictable_validators=1010,
                staking_module=StakingModuleFactory.build(priority_exit_share_threshold=0.2 * 10000),
            ),
        ),
        NodeOperatorStatsFactory.build(
            module_stats=ModuleStatsFactory.build(
                predictable_validators=3000,
                staking_module=StakingModuleFactory.build(priority_exit_share_threshold=0.2 * 10000),
            ),
        ),
        NodeOperatorStatsFactory.build(
            module_stats=ModuleStatsFactory.build(
                predictable_validators=3000,
                staking_module=StakingModuleFactory.build(priority_exit_share_threshold=1 * 10000),
            ),
        ),
        NodeOperatorStatsFactory.build(
            module_stats=ModuleStatsFactory.build(
                predictable_validators=5000,
                staking_module=StakingModuleFactory.build(priority_exit_share_threshold=1 * 10000),
            ),
        ),
    ]

    sorted_nos = sorted(nos, key=lambda x: -iterator._max_share_rate_coefficient_predicate(x))

    assert sorted_nos[0] == nos[1]
    assert sorted_nos[1] in [nos[2], nos[0]]
    assert sorted_nos[2] in [nos[2], nos[0]]
    assert sorted_nos[3] == nos[3]


@pytest.mark.unit
def test_get_remaining_forced_validators(iterator):
    iterator.max_validators_to_exit = 10
    iterator.index = 5

    sm = StakingModuleFactory.build(id=1)

    iterator.node_operators_stats = {
        (1, 1): NodeOperatorStatsFactory.build(
            predictable_validators=10,
            force_exit_to=None,
            node_operator=NodeOperatorFactory.build(id=1, staking_module=sm),
        ),
        (1, 2): NodeOperatorStatsFactory.build(
            predictable_validators=10,
            force_exit_to=9,
            node_operator=NodeOperatorFactory.build(id=2, staking_module=sm),
        ),
        (1, 3): NodeOperatorStatsFactory.build(
            predictable_validators=10,
            force_exit_to=9,
            node_operator=NodeOperatorFactory.build(id=3, staking_module=sm),
        ),
        (1, 4): NodeOperatorStatsFactory.build(
            predictable_validators=10,
            force_exit_to=9,
            node_operator=NodeOperatorFactory.build(id=4, staking_module=sm),
        ),
        (1, 5): NodeOperatorStatsFactory.build(
            predictable_validators=10,
            force_exit_to=9,
            node_operator=NodeOperatorFactory.build(id=5, staking_module=sm),
        ),
    }

    iterator.exitable_validators = {
        (1, 1): [],
        (1, 2): [LidoValidatorFactory.build(index=5)],
        (1, 3): [LidoValidatorFactory.build(index=3)],
        (1, 4): [LidoValidatorFactory.build(index=4)],
        (1, 5): [],
    }

    def _eject(self, gid):
        self.node_operators_stats[gid].predictable_validators -= 1
        return self.exitable_validators[gid][0]

    iterator._eject_validator = MethodType(_eject, iterator)

    vals = iterator.get_remaining_forced_validators()

    assert len(vals) == 3

    assert vals[0][1].index == 3
    assert vals[1][1].index == 4
    assert vals[2][1].index == 5

    iterator.node_operators_stats[1, 2].predictable_validators = 11

    iterator.max_validators_to_exit = 10
    iterator.index = 9

    vals = iterator.get_remaining_forced_validators()
    assert len(vals) == 1


@pytest.mark.unit
def test_get_remaining_forced_validators_all_predictable(iterator):
    iterator.max_validators_to_exit = 10
    iterator.index = 5
    sm = StakingModuleFactory.build(id=1)

    iterator.node_operators_stats = {
        (1, 1): NodeOperatorStatsFactory.build(
            predictable_validators=10,
            force_exit_to=9,
            node_operator=NodeOperatorFactory.build(id=1, staking_module=sm),
        ),
        (1, 2): NodeOperatorStatsFactory.build(
            predictable_validators=10,
            force_exit_to=9,
            node_operator=NodeOperatorFactory.build(id=2, staking_module=sm),
        ),
    }

    iterator.exitable_validators = {
        (1, 1): [],
        (1, 2): [],
    }

    vals = iterator.get_remaining_forced_validators()

    assert len(vals) == 0


@pytest.mark.unit
def test_get_remaining_forced_validators_no_node_operators(iterator):
    iterator.node_operators_stats = {}
    vals = iterator.get_remaining_forced_validators()
    assert len(vals) == 0


@pytest.mark.unit
def test_get_remaining_forced_validators_no_more_place_in_report(iterator):
    iterator.max_validators_to_exit = 10
    iterator.index = 10

    iterator.node_operators_stats = {
        (1, 1): NodeOperatorStatsFactory.build(
            predictable_validators=10,
            force_exit_to=5,
            node_operator=NodeOperatorFactory.build(id=1, staking_module=StakingModuleFactory.build(id=1)),
        ),
    }

    iterator.exitable_validators = {
        (1, 1): [LidoValidatorFactory.build(index=5)],
    }

    vals = iterator.get_remaining_forced_validators()
    assert len(vals) == 0


@pytest.mark.unit
def test_lowest_validators_index_predicate(iterator):
    iterator.node_operators_stats = {
        (1, 1): NodeOperatorStatsFactory.build(
            predictable_validators=10,
            force_exit_to=None,
            node_operator=NodeOperatorFactory.build(id=1, staking_module=StakingModuleFactory.build(id=1)),
        ),
        (1, 2): NodeOperatorStatsFactory.build(
            predictable_validators=10,
            force_exit_to=None,
            node_operator=NodeOperatorFactory.build(id=2, staking_module=StakingModuleFactory.build(id=1)),
        ),
    }

    iterator.exitable_validators = {
        (1, 1): [LidoValidatorFactory.build(index=5)],
        (1, 2): [LidoValidatorFactory.build(index=10)],
    }

    index = iterator._lowest_validator_index_predicate(iterator.node_operators_stats[(1, 1)])
    assert index == 5

    index = iterator._lowest_validator_index_predicate(iterator.node_operators_stats[(1, 2)])
    assert index == 10
