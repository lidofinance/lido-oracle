import pytest

from src.providers.consensus.typings import ValidatorState, Validator
from src.providers.keys.typings import LidoKey
from src.services.exit_order import ValidatorsExit, NodeOperatorPredictableState
from src.web3py.extentions.lido_validators import LidoValidator, StakingModuleId, NodeOperatorId

FAR_FUTURE_EPOCH = 2 ** 64 - 1


@pytest.mark.unit
def test_exit_order_queue():
    # test generator __next__
    pass


@pytest.mark.unit
def test_decrease_node_operator_stats():
    pass


@pytest.mark.unit
def test_predicates():

    def v(module_address, operator, index, activation_epoch) -> LidoValidator:
        validator = object.__new__(LidoValidator)
        validator.key = object.__new__(LidoKey)
        validator.validator = object.__new__(Validator)
        validator.validator.validator = object.__new__(ValidatorState)
        validator.key.moduleAddress = module_address
        validator.key.operatorIndex = operator
        validator.validator.index = index
        validator.validator.validator.activation_epoch = activation_epoch
        return validator

    staking_module_id = {
        '0x0': StakingModuleId(0),
        '0x1': StakingModuleId(1),
        '0x2': StakingModuleId(2),
        '0x3': StakingModuleId(3),
        '0x4': StakingModuleId(4),
        '0x5': StakingModuleId(5),
    }

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

    validators_exit = object.__new__(ValidatorsExit)
    validators_exit.no_index_by_validator = lambda v: (staking_module_id[v.key.moduleAddress], v.key.operatorIndex)
    validators_exit.total_active_validators_count = 500000

    validators_exit.lido_node_operator_stats = {
        (StakingModuleId(0), NodeOperatorId(1)): NodeOperatorPredictableState(1000, 7000, 10, 0),
        (StakingModuleId(0), NodeOperatorId(2)): NodeOperatorPredictableState(1000, 7000, 10, 0),
        (StakingModuleId(1), NodeOperatorId(1)): NodeOperatorPredictableState(1200, 6000, 2, 0),
        (StakingModuleId(1), NodeOperatorId(2)): NodeOperatorPredictableState(1200, 6000, 2, 0),
        (StakingModuleId(2), NodeOperatorId(1)): NodeOperatorPredictableState(1200, 6000, 2, 0),
        (StakingModuleId(2), NodeOperatorId(2)): NodeOperatorPredictableState(998, 7432, None, 0),
        (StakingModuleId(3), NodeOperatorId(1)): NodeOperatorPredictableState(998, 7432, None, 0),
        (StakingModuleId(3), NodeOperatorId(2)): NodeOperatorPredictableState(998, 7432, None, 0),
        (StakingModuleId(4), NodeOperatorId(1)): NodeOperatorPredictableState(100500, 5, 50, 1),
        (StakingModuleId(4), NodeOperatorId(2)): NodeOperatorPredictableState(100500, 2, None, 2),
        (StakingModuleId(5), NodeOperatorId(1)): NodeOperatorPredictableState(100500, 2, None, 2),
    }

    exitable_validators_random_sort.sort(key=lambda validator: ValidatorsExit._predicates(validators_exit, validator))
    exitable_validators_indexes = [v.validator.index for v in exitable_validators_random_sort]

    expected_queue_sort_indexes = [47, 90, 50, 76, 81, 48, 49, 52, 10, 1121, 1122]
    assert exitable_validators_indexes == expected_queue_sort_indexes


@pytest.mark.unit
def test_prepare_lido_node_operator_stats():
    pass


@pytest.mark.unit
def test_get_last_requested_to_exit_indices():
    pass


@pytest.mark.unit
def test_get_delayed_validators_per_operator():
    def v(index, exit_epoch) -> LidoValidator:
        validator = object.__new__(LidoValidator)
        validator.validator = object.__new__(Validator)
        validator.validator.validator = object.__new__(ValidatorState)
        validator.validator.index = index
        validator.validator.validator.exit_epoch = exit_epoch
        return validator

    last_requested_to_exit_indices_per_operator = {
        (StakingModuleId(0), NodeOperatorId(1)): -1,
        (StakingModuleId(0), NodeOperatorId(2)): -1,
        (StakingModuleId(1), NodeOperatorId(1)): -1,
        (StakingModuleId(1), NodeOperatorId(2)): -1,
        (StakingModuleId(2), NodeOperatorId(1)): 10000,
        (StakingModuleId(2), NodeOperatorId(2)): 10000,
        (StakingModuleId(3), NodeOperatorId(1)): 10000,
        (StakingModuleId(3), NodeOperatorId(2)): 10000,
    }
    operator_validators = {
        (StakingModuleId(0), NodeOperatorId(1)): [v(1, 100500), v(2, 100500)],
        (StakingModuleId(0), NodeOperatorId(2)): [v(3, 100500), v(4, 100500)],
        (StakingModuleId(1), NodeOperatorId(1)): [v(5, FAR_FUTURE_EPOCH), v(6, FAR_FUTURE_EPOCH)],
        (StakingModuleId(1), NodeOperatorId(2)): [v(7, FAR_FUTURE_EPOCH), v(8, FAR_FUTURE_EPOCH)],
        (StakingModuleId(2), NodeOperatorId(1)): [v(9, 100500), v(10, 100500)],
        (StakingModuleId(2), NodeOperatorId(2)): [v(11, 100500), v(12, 100500)],
        (StakingModuleId(3), NodeOperatorId(1)): [v(13, FAR_FUTURE_EPOCH), v(14, FAR_FUTURE_EPOCH)],
        (StakingModuleId(3), NodeOperatorId(2)): [v(15, FAR_FUTURE_EPOCH), v(16, FAR_FUTURE_EPOCH)],
    }
    recently_requested_to_exit_indices_per_operator = {
        (StakingModuleId(0), NodeOperatorId(1)): {1, 2},
        (StakingModuleId(0), NodeOperatorId(2)): {},
        (StakingModuleId(1), NodeOperatorId(1)): {5, 6},
        (StakingModuleId(1), NodeOperatorId(2)): {},
        (StakingModuleId(2), NodeOperatorId(1)): {9, 10},
        (StakingModuleId(2), NodeOperatorId(2)): {},
        (StakingModuleId(3), NodeOperatorId(1)): {13, 14},
        (StakingModuleId(3), NodeOperatorId(2)): {},
    }

    delayed = ValidatorsExit._get_delayed_validators_per_operator(
        object.__new__(ValidatorsExit),
        operator_validators,
        recently_requested_to_exit_indices_per_operator,
        last_requested_to_exit_indices_per_operator,
    )

    assert len(delayed) == 1
    assert delayed[(StakingModuleId(3), NodeOperatorId(2))] == 2


@pytest.mark.unit
def test_get_recently_requested_to_exit_indices():
    pass


@pytest.mark.unit
def test_get_last_requested_validator_index():
    pass


@pytest.mark.unit
@pytest.mark.parametrize(
    ('exit_epoch', 'expected'),
    [(100500, True),
     (FAR_FUTURE_EPOCH, False)]
)
def test_is_on_exit(exit_epoch, expected):
    validator = object.__new__(LidoValidator)
    validator.validator = object.__new__(Validator)
    validator.validator.validator = object.__new__(ValidatorState)
    validator.validator.validator.exit_epoch = exit_epoch
    assert ValidatorsExit._is_on_exit(validator) == expected
