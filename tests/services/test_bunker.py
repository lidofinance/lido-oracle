import pytest

from src.modules.submodules.consensus import FrameConfig
from src.providers.consensus.typings import Validator, ValidatorStatus, ValidatorState
from src.services.bunker import BunkerService
from src.typings import EpochNumber

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
    slashed_validators = BunkerService._not_withdrawn_slashed_validators(validators, EpochNumber(15000))
    slashed_validators_indexes = [v.index for v in slashed_validators]
    assert slashed_validators_indexes == expected_indexes


@pytest.mark.unit
def test_get_per_epoch_buckets():

    validators = [
        Validator('0', '1', ValidatorStatus.ACTIVE_SLASHED, ValidatorState('', '', '', True, '', '', '1', '18192')),
        Validator('0', '1', ValidatorStatus.ACTIVE_SLASHED, ValidatorState('', '', '', True, '', '', '18000', '18192')),
    ]

    per_epoch_buckets = BunkerService._get_per_epoch_buckets(validators, EpochNumber(15000))
    assert len(per_epoch_buckets) == 5001
    assert per_epoch_buckets[EpochNumber(10000)] == validators
    for epoch in range(10001, 15001):
        assert per_epoch_buckets[EpochNumber(epoch)] == [validators[-1]]


@pytest.mark.unit
def test_get_per_epoch_lido_midterm_penalties():
    validators = [
        Validator('0', '1', ValidatorStatus.ACTIVE_SLASHED, ValidatorState('', '', str(32 * 10 ** 9), True, '', '', '1', '18192')),
        Validator('0', '1', ValidatorStatus.ACTIVE_SLASHED, ValidatorState('', '', str(32 * 10 ** 9), True, '', '', '18000', '18192')),
    ]
    total_balance = 32 * 60000 * 10 ** 9

    per_epoch_buckets = BunkerService._get_per_epoch_buckets(validators, EpochNumber(15000))

    per_epoch_lido_midterm_penalties = BunkerService._get_per_epoch_lido_midterm_penalties(
        per_epoch_buckets, validators, total_balance
    )

    # todo: real test
    assert len(per_epoch_lido_midterm_penalties) == 5001


@pytest.mark.unit
def test_get_per_frame_lido_midterm_penalties():
    validators = [
        Validator('0', '1', ValidatorStatus.ACTIVE_SLASHED, ValidatorState('', '', str(32 * 10 ** 9), True, '', '', '1', '18192')),
        Validator('0', '1', ValidatorStatus.ACTIVE_SLASHED, ValidatorState('', '', str(32 * 10 ** 9), True, '', '', '18000', '18192')),
    ]
    total_balance = 32 * 60000 * 10 ** 9

    per_epoch_buckets = BunkerService._get_per_epoch_buckets(validators, EpochNumber(15000))

    per_epoch_lido_midterm_penalties = BunkerService._get_per_epoch_lido_midterm_penalties(
        per_epoch_buckets, validators, total_balance
    )

    per_frame_lido_midterm_penalties = BunkerService._get_per_frame_lido_midterm_penalties(
        per_epoch_lido_midterm_penalties,
        FrameConfig(
            initial_epoch=EpochNumber(0),
            epochs_per_frame=EpochNumber(225),
        )
    )

    # todo: real test
    assert len(per_frame_lido_midterm_penalties) == 23


@pytest.mark.unit
@pytest.mark.parametrize(
    ("epoch_passed", "mean_lido", "mean_total", "expected"),
    [(225, 32 * 152261 * 10 ** 9, 32 * 517310 * 10 ** 9, 530171362946),
     (450, 32 * 152261 * 10 ** 9, 32 * 517310 * 10 ** 9, 1060342725893)]
)
def test_get_normal_cl_rebase(epoch_passed, mean_lido, mean_total, expected):
    normal_cl_rebase = BunkerService._get_normal_cl_rebase(epoch_passed, mean_lido, mean_total)
    assert normal_cl_rebase == expected
