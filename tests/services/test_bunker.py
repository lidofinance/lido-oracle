import pytest

from src.modules.submodules.consensus import FrameConfig
from src.providers.consensus.typings import Validator, ValidatorStatus, ValidatorState
from src.services.bunker import BunkerService, BunkerConfig
from src.typings import EpochNumber

# Static functions


test_data_calculate_real_balance = [
    (
        {'0x0': Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING, ValidatorState('0x0', '', '2', False, '', '', '', '')),
         '0x1': Validator('1', '1', ValidatorStatus.ACTIVE_EXITING, ValidatorState('0x1', '', '3', False, '', '', '', '')),
         '0x2': Validator('2', '1', ValidatorStatus.ACTIVE_SLASHED, ValidatorState('0x2', '', '4', True, '', '', '', ''))},
        3,
    ),
    (
        {'0x0': Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING, ValidatorState('0x0', '', '2', False, '', '', '', '')),
         '0x1': Validator('1', '1', ValidatorStatus.EXITED_SLASHED, ValidatorState('0x1', '', '2', True, '', '', '', ''))},
        2,
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize(("validators", "expected_balance"), test_data_calculate_real_balance)
def test_calculate_real_balance(validators, expected_balance):
    total_effective_balance = BunkerService._calculate_real_balance(validators)
    assert total_effective_balance == expected_balance


test_data_calculate_total_effective_balance = [
    (
        {'0x0': Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING, ValidatorState('0x0', '', '2', False, '', '1', '100500', '')),
         '0x1': Validator('1', '1', ValidatorStatus.ACTIVE_EXITING, ValidatorState('0x1', '', '3', False, '', '1', '100500', '')),
         '0x2': Validator('2', '1', ValidatorStatus.ACTIVE_SLASHED, ValidatorState('0x2', '', '4', True, '', '1', '100500', ''))},
        9,
    ),
    (
        {'0x0': Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING, ValidatorState('0x0', '', '2', False, '', '1', '100500', '')),
         '0x1': Validator('1', '1', ValidatorStatus.EXITED_SLASHED, ValidatorState('0x1', '', '2', True, '', '1', '200', ''))},
        2,
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize(("validators", "expected_balance"), test_data_calculate_total_effective_balance)
def test_calculate_total_active_effective_balance(validators, expected_balance):
    total_effective_balance = BunkerService._calculate_total_active_effective_balance(validators, EpochNumber(15000))
    assert total_effective_balance == expected_balance


test_data_calculate_total_effective_balance = [
    (
        {'0x0': Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING, ValidatorState('0x0', '', '2', True, '', '', '', '15001')),
         '0x1': Validator('1', '1', ValidatorStatus.ACTIVE_EXITING, ValidatorState('0x1', '', '3', True, '', '', '', '15001')),
         '0x2': Validator('2', '1', ValidatorStatus.ACTIVE_SLASHED, ValidatorState('0x2', '', '4', True, '', '', '', '15001'))},
        ['0x0', '0x1', '0x2'],
    ),
    (
        {'0x0': Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING, ValidatorState('0x0', '', '2', True, '', '', '', '15000')),
         '0x1': Validator('1', '1', ValidatorStatus.EXITED_SLASHED, ValidatorState('0x1', '', '2', True, '', '', '', '15000'))},
        [],
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize(("validators", "expected_indexes"), test_data_calculate_total_effective_balance)
def test_not_withdrawn_slashed_validators(validators, expected_indexes):
    slashed_validators = BunkerService._not_withdrawn_slashed_validators(validators, EpochNumber(15000))
    slashed_validators_keys = [*slashed_validators.keys()]
    assert slashed_validators_keys == expected_indexes


all_slashed_validators = {
    '0x0': Validator('0', '1', ValidatorStatus.ACTIVE_SLASHED, ValidatorState('', '', str(32 * 10 ** 9), True, '', '', '1', '18192')),
    '0x1': Validator('1', '1', ValidatorStatus.ACTIVE_SLASHED, ValidatorState('', '', str(32 * 10 ** 9), True, '', '', '18000', '18192')),
    '0x2': Validator('2', '1', ValidatorStatus.ACTIVE_SLASHED, ValidatorState('', '', str(32 * 10 ** 9), True, '', '', '1', '18192')),
}
for i in range(int([*all_slashed_validators.values()][-1].index) + 1, int([*all_slashed_validators.values()][-1].index) + 1000):
    all_slashed_validators[f"0x{i}"] = (
        Validator(str(i), '1', ValidatorStatus.ACTIVE_SLASHED, ValidatorState('', '', str(32 * 10 ** 9), True, '', '', '1', '18192'))
    )


@pytest.mark.unit
def test_get_per_epoch_buckets():
    expected_buckets = 3193
    expected_determined_slashed_epoch = EpochNumber(10000)
    expected_possible_slashed_epochs = range(
        expected_determined_slashed_epoch - expected_buckets + 1, expected_determined_slashed_epoch
    )

    per_epoch_buckets = BunkerService._get_per_epoch_buckets(all_slashed_validators, EpochNumber(15000))

    assert len(per_epoch_buckets) == expected_buckets
    assert per_epoch_buckets[expected_determined_slashed_epoch] == all_slashed_validators
    for epoch in expected_possible_slashed_epochs:
        assert per_epoch_buckets[EpochNumber(epoch)] == {'0x1': all_slashed_validators['0x1']}


@pytest.mark.unit
def test_get_bounded_slashed_validators():
    determined_slashed_epoch = EpochNumber(10000)
    per_epoch_buckets = BunkerService._get_per_epoch_buckets(all_slashed_validators, EpochNumber(15000))

    bounded_slashed_validators = BunkerService._get_bounded_slashed_validators(
        per_epoch_buckets, determined_slashed_epoch
    )

    assert len(bounded_slashed_validators) == len(all_slashed_validators)


@pytest.mark.unit
def test_get_per_epoch_lido_midterm_penalties():
    lido_slashed_validators = {
        '0x0': all_slashed_validators['0x0'],
        '0x1': all_slashed_validators['0x1'],
        '0x2': all_slashed_validators['0x2']
    }
    total_balance = 32 * 60000 * 10 ** 9
    per_epoch_buckets = BunkerService._get_per_epoch_buckets(all_slashed_validators, EpochNumber(15000))

    per_epoch_lido_midterm_penalties = BunkerService._get_per_epoch_lido_midterm_penalties(
        object.__new__(BunkerService), per_epoch_buckets, lido_slashed_validators, total_balance
    )

    assert len(per_epoch_lido_midterm_penalties) == 1
    assert per_epoch_lido_midterm_penalties[EpochNumber(14096)] == {'0x0': 1000000000, '0x1': 0, '0x2': 1000000000}


@pytest.mark.unit
def test_get_per_frame_lido_midterm_penalties():
    lido_slashed_validators = {
        '0x0': all_slashed_validators['0x0'],
        '0x1': all_slashed_validators['0x1'],
        '0x2': all_slashed_validators['0x2']
    }
    total_balance = 32 * 60000 * 10 ** 9
    per_epoch_buckets = BunkerService._get_per_epoch_buckets(all_slashed_validators, EpochNumber(15000))
    per_epoch_lido_midterm_penalties = BunkerService._get_per_epoch_lido_midterm_penalties(
        object.__new__(BunkerService), per_epoch_buckets, lido_slashed_validators, total_balance
    )

    per_frame_lido_midterm_penalties = BunkerService._get_per_frame_lido_midterm_penalties(
        object.__new__(BunkerService),
        per_epoch_lido_midterm_penalties,
        FrameConfig(
            initial_epoch=EpochNumber(0),
            epochs_per_frame=EpochNumber(225),
        )
    )

    assert len(per_frame_lido_midterm_penalties) == 1
    assert per_frame_lido_midterm_penalties[0] == 2000000000


@pytest.mark.unit
@pytest.mark.parametrize(
    ("epoch", "expected_frame"),
    [(EpochNumber(0), 0),
     (EpochNumber(224), 0),
     (EpochNumber(225), 1),
     (EpochNumber(449), 1),
     (EpochNumber(450), 2)]
)
def test_get_frame_by_epoch(epoch, expected_frame):
    frame_config = FrameConfig(
        initial_epoch=EpochNumber(0),
        epochs_per_frame=EpochNumber(225),
    )
    frame_by_epoch = BunkerService._get_frame_by_epoch(epoch, frame_config)
    assert frame_by_epoch == expected_frame


@pytest.mark.unit
@pytest.mark.parametrize(
    ("epoch_passed", "mean_lido", "mean_total", "expected"),
    [(225, 32 * 152261 * 10 ** 9, 32 * 517310 * 10 ** 9, 490787204556),
     (450, 32 * 152261 * 10 ** 9, 32 * 517310 * 10 ** 9, 981574409112)]
)
def test_calculate_normal_cl_rebase(epoch_passed, mean_lido, mean_total, expected):
    bunker = object.__new__(BunkerService)
    bunker.b_conf = object.__new__(BunkerConfig)
    bunker.b_conf.normalized_cl_per_epoch = 64
    bunker.b_conf.normalized_cl_mistake = 0.1
    normal_cl_rebase = bunker._calculate_normal_cl_rebase(epoch_passed, mean_lido, mean_total)
    assert normal_cl_rebase == expected
