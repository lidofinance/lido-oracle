from unittest.mock import Mock

import pytest

from src.providers.consensus.types import ValidatorState
from src.providers.keys.types import LidoKey
from src.services.exit_order.iterator import ExitOrderIterator
from src.services.exit_order.iterator_state import NodeOperatorPredictableState, ExitOrderIteratorStateService
from src.web3py.extensions.lido_validators import LidoValidator, StakingModuleId, NodeOperatorId
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import ChainConfigFactory, OracleReportLimitsFactory
from tests.factory.no_registry import LidoValidatorFactory


@pytest.mark.unit
def test_predicates():
    def v(module_address, operator: int, index, activation_epoch) -> LidoValidator:
        validator = object.__new__(LidoValidator)
        validator.lido_id = object.__new__(LidoKey)
        validator.validator = object.__new__(ValidatorState)
        validator.lido_id.moduleAddress = module_address
        validator.lido_id.operatorIndex = NodeOperatorId(operator)
        validator.index = index
        validator.validator.activation_epoch = activation_epoch
        return validator

    exitable_validators_random_sort = [
        v('0x1', 2, 76, 1200),
        v('0x4', 2, 1121, 3210),
        v('0x5', 1, 1122, 3210),
        v('0x2', 1, 81, 1400),
        v('0x2', 2, 48, 781),
        v('0x3', 1, 49, 990),
        v('0x4', 1, 10, 231),
        v('0x0', 2, 90, 1500),
        v('0x1', 1, 50, 1000),
        v('0x3', 2, 52, 1003),
        v('0x0', 1, 47, 500),
    ]

    validators_exit = object.__new__(ExitOrderIterator)
    validators_exit.operator_network_penetration_threshold = 0.01
    validators_exit.staking_module_id = {
        '0x0': StakingModuleId(0),
        '0x1': StakingModuleId(1),
        '0x2': StakingModuleId(2),
        '0x3': StakingModuleId(3),
        '0x4': StakingModuleId(4),
        '0x5': StakingModuleId(5),
    }
    validators_exit.total_predictable_validators_count = 500000

    validators_exit.lido_node_operator_stats = {
        (StakingModuleId(0), NodeOperatorId(1)): NodeOperatorPredictableState(1000, 7000, True, 10, 0),
        (StakingModuleId(0), NodeOperatorId(2)): NodeOperatorPredictableState(1000, 7000, True, 10, 0),
        (StakingModuleId(1), NodeOperatorId(1)): NodeOperatorPredictableState(1200, 6000, True, 2, 0),
        (StakingModuleId(1), NodeOperatorId(2)): NodeOperatorPredictableState(1200, 6000, True, 2, 0),
        (StakingModuleId(2), NodeOperatorId(1)): NodeOperatorPredictableState(1200, 6000, True, 2, 0),
        (StakingModuleId(2), NodeOperatorId(2)): NodeOperatorPredictableState(998, 7432, False, 0, 0),
        (StakingModuleId(3), NodeOperatorId(1)): NodeOperatorPredictableState(998, 7432, False, 0, 0),
        (StakingModuleId(3), NodeOperatorId(2)): NodeOperatorPredictableState(998, 7432, False, 0, 0),
        (StakingModuleId(4), NodeOperatorId(1)): NodeOperatorPredictableState(100500, 5, True, 50, 1),
        (StakingModuleId(4), NodeOperatorId(2)): NodeOperatorPredictableState(100500, 2, False, 0, 2),
        (StakingModuleId(5), NodeOperatorId(1)): NodeOperatorPredictableState(100500, 2, False, 0, 2),
    }

    exitable_validators_random_sort.sort(
        key=lambda validator: ExitOrderIterator._predicates(validators_exit, validator)
    )
    exitable_validators_indexes = [v.index for v in exitable_validators_random_sort]

    expected_queue_sort_indexes = [47, 90, 50, 76, 81, 48, 49, 52, 10, 1121, 1122]
    assert exitable_validators_indexes == expected_queue_sort_indexes


@pytest.mark.unit
def test_decrease_node_operator_stats():
    def v(module_address, operator: int, index, activation_epoch) -> LidoValidator:
        validator = object.__new__(LidoValidator)
        validator.lido_id = object.__new__(LidoKey)
        validator.validator = object.__new__(ValidatorState)
        validator.lido_id.moduleAddress = module_address
        validator.lido_id.operatorIndex = NodeOperatorId(operator)
        validator.index = index
        validator.validator.activation_epoch = activation_epoch
        return validator

    exitable_validators = [
        v('0x1', 2, 76, 1200),
        v('0x4', 2, 1121, 5000),
    ]

    validator_exit = object.__new__(ExitOrderIterator)
    validator_exit.blockstamp = ReferenceBlockStampFactory.build(ref_epoch=4445)
    validator_exit.total_predictable_validators_count = 500000
    validator_exit.staking_module_id = {
        '0x0': StakingModuleId(0),
        '0x1': StakingModuleId(1),
        '0x2': StakingModuleId(2),
        '0x3': StakingModuleId(3),
        '0x4': StakingModuleId(4),
        '0x5': StakingModuleId(5),
    }
    validator_exit.lido_node_operator_stats = {
        (StakingModuleId(0), NodeOperatorId(1)): NodeOperatorPredictableState(1000, 7000, True, 10, 0),
        (StakingModuleId(0), NodeOperatorId(2)): NodeOperatorPredictableState(1000, 7000, True, 10, 0),
        (StakingModuleId(1), NodeOperatorId(1)): NodeOperatorPredictableState(1200, 6000, True, 2, 0),
        (StakingModuleId(1), NodeOperatorId(2)): NodeOperatorPredictableState(3245, 6000, True, 2, 0),
        (StakingModuleId(2), NodeOperatorId(1)): NodeOperatorPredictableState(1200, 6000, True, 2, 0),
        (StakingModuleId(2), NodeOperatorId(2)): NodeOperatorPredictableState(998, 7432, False, 0, 0),
        (StakingModuleId(3), NodeOperatorId(1)): NodeOperatorPredictableState(998, 7432, False, 0, 0),
        (StakingModuleId(3), NodeOperatorId(2)): NodeOperatorPredictableState(998, 7432, False, 0, 0),
        (StakingModuleId(4), NodeOperatorId(1)): NodeOperatorPredictableState(100500, 5, True, 50, 1),
        (StakingModuleId(4), NodeOperatorId(2)): NodeOperatorPredictableState(100500, 2, False, 0, 2),
        (StakingModuleId(5), NodeOperatorId(1)): NodeOperatorPredictableState(100500, 2, False, 0, 2),
    }

    module_operator = validator_exit._decrease_node_operator_stats(exitable_validators[0])
    expected_after_decrease_first = NodeOperatorPredictableState(0, 5999, True, 2, 0)
    assert module_operator == (StakingModuleId(1), NodeOperatorId(2))
    assert validator_exit.total_predictable_validators_count == 499999
    assert (
        validator_exit.lido_node_operator_stats[(StakingModuleId(1), NodeOperatorId(2))]
        == expected_after_decrease_first
    )

    module_operator = validator_exit._decrease_node_operator_stats(exitable_validators[1])
    expected_after_decrease_second = NodeOperatorPredictableState(100500, 1, False, 0, 2)
    assert module_operator == (StakingModuleId(4), NodeOperatorId(2))
    assert validator_exit.total_predictable_validators_count == 499998
    assert (
        validator_exit.lido_node_operator_stats[(StakingModuleId(4), NodeOperatorId(2))]
        == expected_after_decrease_second
    )


@pytest.fixture
def mock_exit_order_iterator_state_service(monkeypatch):
    class MockedExitOrderIteratorStateService(ExitOrderIteratorStateService):
        pass

    MockedExitOrderIteratorStateService.get_operator_network_penetration_threshold = lambda *_: 0.05
    MockedExitOrderIteratorStateService.get_operators_with_last_exited_validator_indexes = lambda *_: {}
    MockedExitOrderIteratorStateService.get_exitable_lido_validators = lambda *_: []
    MockedExitOrderIteratorStateService.prepare_lido_node_operator_stats = lambda *_: {}
    MockedExitOrderIteratorStateService.get_total_predictable_validators_count = lambda *_: 0

    monkeypatch.setattr(
        'src.services.exit_order.iterator.ExitOrderIteratorStateService', MockedExitOrderIteratorStateService
    )


@pytest.mark.unit
def test_exit_order_iterator_iter(web3, lido_validators, contracts, mock_exit_order_iterator_state_service):
    web3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits = Mock(
        return_value=OracleReportLimitsFactory.build(max_validator_exit_requests_per_report=100)
    )

    iterator = ExitOrderIterator(web3, ReferenceBlockStampFactory.build(), ChainConfigFactory.build())
    web3.lido_validators.get_lido_node_operators = lambda _: []
    web3.lido_validators.get_lido_validators_by_node_operators = lambda _: []

    iterator.__iter__()

    assert iterator.exitable_lido_validators == []
    assert iterator.left_queue_count == 0
    assert iterator.lido_node_operator_stats == {}
    assert iterator.max_validators_to_exit == 100
    assert iterator.operator_network_penetration_threshold == 0.05
    assert iterator.staking_module_id == {}
    assert iterator.total_predictable_validators_count == 0


@pytest.mark.unit
def test_exit_order_iterator_next(web3, lido_validators, contracts, mock_exit_order_iterator_state_service):
    web3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits = Mock(
        return_value=OracleReportLimitsFactory.build(max_validator_exit_requests_per_report=100)
    )

    iterator = ExitOrderIterator(web3, ReferenceBlockStampFactory.build(), ChainConfigFactory.build())
    web3.lido_validators.get_lido_node_operators = lambda _: []
    web3.lido_validators.get_lido_validators_by_node_operators = lambda _: []

    iterator.__iter__()

    iterator.left_queue_count = 101

    with pytest.raises(StopIteration):
        # left_queue_count > max_validators_to_exit
        iterator.__next__()

    iterator.left_queue_count = 0

    with pytest.raises(StopIteration):
        # no exitable validators
        iterator.__next__()

    validator = LidoValidatorFactory.build(index=0)
    validator.validator.activation_epoch = 0
    iterator.exitable_lido_validators = [validator]
    iterator.lido_node_operator_stats = {
        (0, 1): NodeOperatorPredictableState(1000, 7000, True, 10, 0),
    }
    iterator.total_predictable_validators_count = 100
    ExitOrderIterator.operator_index_by_validator = lambda *_: (0, 1)

    popped = iterator.__next__()

    assert popped == ((0, 1), validator)
    assert iterator.lido_node_operator_stats[(0, 1)] == NodeOperatorPredictableState(
        predictable_validators_total_age=-8195,
        predictable_validators_count=6999,
        targeted_validators_limit_is_enabled=True,
        targeted_validators_limit_count=10,
        delayed_validators_count=0,
    )
    assert iterator.total_predictable_validators_count == 99
