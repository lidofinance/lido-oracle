import pytest

from src.providers.consensus.typings import Validator, ValidatorStatus, ValidatorState
from src.typings import EpochNumber
from src.utils.validator_state import calculate_active_effective_balance_sum

test_data_calculate_total_effective_balance = [
    (
        {'0x0': Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING,
                          ValidatorState('0x0', '', '2', False, '', '1', '100500', '')),
         '0x1': Validator('1', '1', ValidatorStatus.ACTIVE_EXITING,
                          ValidatorState('0x1', '', '3', False, '', '1', '100500', '')),
         '0x2': Validator('2', '1', ValidatorStatus.ACTIVE_SLASHED,
                          ValidatorState('0x2', '', '4', True, '', '1', '100500', ''))},
        9,
    ),
    (
        {'0x0': Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING,
                          ValidatorState('0x0', '', '2', False, '', '1', '100500', '')),
         '0x1': Validator('1', '1', ValidatorStatus.EXITED_SLASHED,
                          ValidatorState('0x1', '', '2', True, '', '1', '200', ''))},
        2,
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize(("validators", "expected_balance"), test_data_calculate_total_effective_balance)
def test_calculate_total_active_effective_balance(validators, expected_balance):
    total_effective_balance = calculate_active_effective_balance_sum(validators.values(), EpochNumber(15000))
    assert total_effective_balance == expected_balance
