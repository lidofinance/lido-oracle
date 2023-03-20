import pytest

from src.constants import FAR_FUTURE_EPOCH
from src.providers.consensus.typings import Validator, ValidatorStatus, ValidatorState
from src.typings import EpochNumber
from src.utils.validator_state import (
    calculate_total_active_effective_balance,
    is_on_exit,
    get_validator_age,
    calculate_active_effective_balance_sum
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("validators", "expected_balance"),
    [
        ([], 1 * 10 ** 9),
        (
            [Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING,
                              ValidatorState('0x0', '', str(32 * 10 ** 9), False, '', '15000', '15001', '')),
             Validator('1', '1', ValidatorStatus.ACTIVE_EXITING,
                              ValidatorState('0x1', '', str(31 * 10 ** 9), False, '', '14999', '15000', '')),
             Validator('2', '1', ValidatorStatus.ACTIVE_SLASHED,
                              ValidatorState('0x2', '', str(31 * 10 ** 9), True, '', '15000', '15001', ''))],
            63 * 10 ** 9,
        ),
        (
            [
                Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING,
                              ValidatorState('0x0', '', str(32 * 10 ** 9), False, '', '14000', '14999', '')),
                Validator('1', '1', ValidatorStatus.EXITED_SLASHED,
                              ValidatorState('0x1', '', str(32 * 10 ** 9), True, '', '15000', '15000', ''))
            ],
            1 * 10 ** 9,
        ),
    ]
)
def test_calculate_total_active_effective_balance(validators, expected_balance):
    total_effective_balance = calculate_total_active_effective_balance(validators, EpochNumber(15000))
    assert total_effective_balance == expected_balance

@pytest.mark.unit
@pytest.mark.parametrize(
    ("validators", "expected_balance"),
    [
        ([], 0),
        (
            [Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING,
                              ValidatorState('0x0', '', str(32 * 10 ** 9), False, '', '15000', '15001', '')),
             Validator('1', '1', ValidatorStatus.ACTIVE_EXITING,
                              ValidatorState('0x1', '', str(31 * 10 ** 9), False, '', '14999', '15000', '')),
             Validator('2', '1', ValidatorStatus.ACTIVE_SLASHED,
                              ValidatorState('0x2', '', str(31 * 10 ** 9), True, '', '15000', '15001', ''))],
            63 * 10 ** 9,
        ),
        (
            [
                Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING,
                              ValidatorState('0x0', '', str(32 * 10 ** 9), False, '', '14000', '14999', '')),
                Validator('1', '1', ValidatorStatus.EXITED_SLASHED,
                              ValidatorState('0x1', '', str(32 * 10 ** 9), True, '', '15000', '15000', ''))
            ],
            0,
        ),
    ]
)
def test_calculate_active_effective_balance_sum(validators, expected_balance):
    total_effective_balance = calculate_active_effective_balance_sum(validators, EpochNumber(15000))
    assert total_effective_balance == expected_balance


@pytest.mark.unit
@pytest.mark.parametrize(
    ('exit_epoch', 'expected'),
    [(100500, True),
     (FAR_FUTURE_EPOCH, False)]
)
def test_is_on_exit(exit_epoch, expected):
    validator = object.__new__(Validator)
    validator.validator = object.__new__(ValidatorState)
    validator.validator.exit_epoch = exit_epoch
    assert is_on_exit(validator) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ('validator_activation_epoch', 'ref_epoch', 'expected_result'),
    [
        (100, 100, 0),
        (100, 101, 1),
        (100, 99, 0),
    ]
)
def test_get_validator_age(validator_activation_epoch, ref_epoch, expected_result):
    validator = object.__new__(Validator)
    validator.validator = object.__new__(ValidatorState)
    validator.validator.activation_epoch = validator_activation_epoch
    assert get_validator_age(validator, ref_epoch) == expected_result
