import pytest

from src.providers.consensus.typings import Validator, ValidatorStatus, ValidatorState
from src.services.bunker import BunkerService


# Static functions

test_data_calculate_total_effective_balance = [
    (
        [Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING, ValidatorState('', '', '2', False, '', '', '', '')),
         Validator('1', '1', ValidatorStatus.ACTIVE_EXITING, ValidatorState('', '', '3', False, '', '', '', '')),
         Validator('2', '1', ValidatorStatus.ACTIVE_SLASHED, ValidatorState('', '', '4', True, '', '', '', ''))],
        9,
    ),
    (
        [Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING, ValidatorState('', '', '2', False, '', '', '', '')),
         Validator('1', '1', ValidatorStatus.EXITED_SLASHED, ValidatorState('', '', '2', True, '', '', '', ''))],
        2,
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize(("validators", "expected_balance"), test_data_calculate_total_effective_balance)
def test_calculate_total_effective_balance(validators, expected_balance):
    total_effective_balance = BunkerService._calculate_total_effective_balance(validators)
    assert total_effective_balance == expected_balance


test_data_calculate_total_effective_balance = [
    (
        [Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING, ValidatorState('', '', '2', True, '', '', '', '15001')),
         Validator('1', '1', ValidatorStatus.ACTIVE_EXITING, ValidatorState('', '', '3', True, '', '', '', '15001')),
         Validator('2', '1', ValidatorStatus.ACTIVE_SLASHED, ValidatorState('', '', '4', True, '', '', '', '15001'))],
        ['0', '1', '2'],
    ),
    (
        [Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING, ValidatorState('', '', '2', True, '', '', '', '15000')),
         Validator('1', '1', ValidatorStatus.EXITED_SLASHED, ValidatorState('', '', '2', True, '', '', '', '15000'))],
        [],
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize(("validators", "expected_indexes"), test_data_calculate_total_effective_balance)
def test_not_withdrawn_slashed_validators(validators, expected_indexes):
    slashed_validators = BunkerService._not_withdrawn_slashed_validators(validators, 15000)
    slashed_validators_indexes = [v.index for v in slashed_validators]
    assert slashed_validators_indexes == expected_indexes


test_data_detect_slashing_epoch_range = [
    (
        Validator('0', '1', ValidatorStatus.ACTIVE_SLASHED, ValidatorState('', '', '', True, '', '', '1', '18192')),
        range(10000, 10001)
    ),
    (
        Validator('0', '1', ValidatorStatus.ACTIVE_SLASHED, ValidatorState('', '', '', True, '', '', '18000', '18192')),
        range(10000, 15001)
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize(("validator", "expected_range"), test_data_detect_slashing_epoch_range)
def test_detect_slashing_epoch_range(validator, expected_range):
    slashing_epoch_range = BunkerService._detect_slashing_epoch_range(validator, 15000)
    assert slashing_epoch_range == expected_range


