import pytest

from src.providers.consensus.typings import ValidatorState
from src.services.exit_order import ValidatorsExit
from src.web3py.extentions.lido_validators import LidoValidator

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
    # _predicates
    # _operator_delayed_validators
    # _operator_targeted_validators
    # _operator_stake_weight
    # _operator_predictable_validators
    # _validator_activation_epoch
    # _validator_index
    pass


@pytest.mark.unit
def test_prepare_lido_node_operator_stats():
    pass


@pytest.mark.unit
def test_get_last_requested_to_exit_indices():
    pass


@pytest.mark.unit
def test_get_delayed_validators_per_operator():
    pass


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
    validator.validator = object.__new__(ValidatorState)
    validator.validator.exit_epoch = exit_epoch
    assert ValidatorsExit._is_on_exit(validator) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ('activation_epoch', 'expected'),
    [(100500, False),
     (FAR_FUTURE_EPOCH, True)]
)
def test_is_pending(activation_epoch, expected):
    validator = object.__new__(LidoValidator)
    validator.validator = object.__new__(ValidatorState)
    validator.validator.activation_epoch = activation_epoch
    assert ValidatorsExit._is_pending(validator) == expected
