import pytest

from src.modules.submodules.consensus import FrameConfig
from src.providers.consensus.typings import Validator, ValidatorStatus, ValidatorState
from src.services.bunker_cases.midterm_slashing_penalty import MidtermSlashingPenalty
from src.typings import EpochNumber
from tests.modules.accounting.bunker.conftest import simple_blockstamp


@pytest.mark.unit
@pytest.mark.parametrize(
    ("lido_validators_range", "frame_cl_rebase", "expected_is_high_midterm_slashing_penalty"),
    [
        ((0, 3), 100, False),         # lido is not slashed
        ((3, 6), 2999999999, True),   # penalty greater than rebase
        ((3, 6), 3000000000, False),  # penalty equal than rebase
        ((3, 6), 3000000001, False),  # penalty less than rebase
    ]
)
def test_is_high_midterm_slashing_penalty(
    bunker,
    mock_get_validators,
    lido_validators_range,
    frame_cl_rebase,
    expected_is_high_midterm_slashing_penalty
):
    blockstamp = simple_blockstamp(1000, '0x1000')
    _from, _to = lido_validators_range
    frame_config = FrameConfig(
        initial_epoch=EpochNumber(0),
        epochs_per_frame=EpochNumber(225),
        fast_lane_length_slots=0,
    )
    lido_validators = {
        v.validator.pubkey: v for v in bunker.w3.cc.get_validators(blockstamp)[_from:_to]
    }
    all_validators = {
        v.validator.pubkey: v for v in bunker.w3.cc.get_validators(blockstamp)
    }

    result = MidtermSlashingPenalty.is_high_midterm_slashing_penalty(
        blockstamp, frame_config, all_validators, lido_validators, frame_cl_rebase
    )
    assert result == expected_is_high_midterm_slashing_penalty


test_data_calculate_real_balance = [
    (
        {'0x0': Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING,
                          ValidatorState('0x0', '', '2', False, '', '', '', '')),
         '0x1': Validator('1', '1', ValidatorStatus.ACTIVE_EXITING,
                          ValidatorState('0x1', '', '3', False, '', '', '', '')),
         '0x2': Validator('2', '1', ValidatorStatus.ACTIVE_SLASHED,
                          ValidatorState('0x2', '', '4', True, '', '', '', ''))},
        3,
    ),
    (
        {'0x0': Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING,
                          ValidatorState('0x0', '', '2', False, '', '', '', '')),
         '0x1': Validator('1', '1', ValidatorStatus.EXITED_SLASHED,
                          ValidatorState('0x1', '', '2', True, '', '', '', ''))},
        2,
    ),
]


test_data_calculate_total_effective_balance = [
    (
        {'0x0': Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING,
                          ValidatorState('0x0', '', '2', True, '', '', '', '15001')),
         '0x1': Validator('1', '1', ValidatorStatus.ACTIVE_EXITING,
                          ValidatorState('0x1', '', '3', True, '', '', '', '15001')),
         '0x2': Validator('2', '1', ValidatorStatus.ACTIVE_SLASHED,
                          ValidatorState('0x2', '', '4', True, '', '', '', '15001'))},
        ['0x0', '0x1', '0x2'],
    ),
    (
        {'0x0': Validator('0', '1', ValidatorStatus.ACTIVE_ONGOING,
                          ValidatorState('0x0', '', '2', True, '', '', '', '15000')),
         '0x1': Validator('1', '1', ValidatorStatus.EXITED_SLASHED,
                          ValidatorState('0x1', '', '2', True, '', '', '', '15000'))},
        [],
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize(("validators", "expected_indexes"), test_data_calculate_total_effective_balance)
def test_not_withdrawn_slashed_validators(validators, expected_indexes):
    slashed_validators = MidtermSlashingPenalty.not_withdrawn_slashed_validators(validators, EpochNumber(15000))
    slashed_validators_keys = [*slashed_validators.keys()]
    assert slashed_validators_keys == expected_indexes


all_slashed_validators = {
    '0x0': Validator('0', '1', ValidatorStatus.ACTIVE_SLASHED,
                     ValidatorState('', '', str(32 * 10 ** 9), True, '', '', '1', '18192')),
    '0x1': Validator('1', '1', ValidatorStatus.ACTIVE_SLASHED,
                     ValidatorState('', '', str(32 * 10 ** 9), True, '', '', '18000', '18192')),
    '0x2': Validator('2', '1', ValidatorStatus.ACTIVE_SLASHED,
                     ValidatorState('', '', str(32 * 10 ** 9), True, '', '', '1', '18192')),
}
for i in range(int([*all_slashed_validators.values()][-1].index) + 1,
               int([*all_slashed_validators.values()][-1].index) + 1000):
    all_slashed_validators[f"0x{i}"] = (
        Validator(str(i), '1', ValidatorStatus.ACTIVE_SLASHED,
                  ValidatorState('', '', str(32 * 10 ** 9), True, '', '', '1', '18192'))
    )


@pytest.mark.unit
def test_get_per_epoch_buckets():
    expected_buckets = 3193
    expected_determined_slashed_epoch = EpochNumber(10000)
    expected_possible_slashed_epochs = range(
        expected_determined_slashed_epoch - expected_buckets + 1, expected_determined_slashed_epoch
    )

    per_epoch_buckets = MidtermSlashingPenalty.get_per_epoch_buckets(all_slashed_validators, EpochNumber(15000))

    assert len(per_epoch_buckets) == expected_buckets
    assert per_epoch_buckets[expected_determined_slashed_epoch] == all_slashed_validators
    for epoch in expected_possible_slashed_epochs:
        assert per_epoch_buckets[EpochNumber(epoch)] == {'0x1': all_slashed_validators['0x1']}


@pytest.mark.unit
def test_get_bounded_slashed_validators():
    determined_slashed_epoch = EpochNumber(10000)
    per_epoch_buckets = MidtermSlashingPenalty.get_per_epoch_buckets(all_slashed_validators, EpochNumber(15000))

    bounded_slashed_validators = MidtermSlashingPenalty.get_bound_slashed_validators(
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
    per_epoch_buckets = MidtermSlashingPenalty.get_per_epoch_buckets(all_slashed_validators, EpochNumber(15000))

    per_epoch_lido_midterm_penalties = MidtermSlashingPenalty.get_per_epoch_lido_midterm_penalties(
        per_epoch_buckets, lido_slashed_validators, total_balance
    )

    assert len(per_epoch_lido_midterm_penalties) == 1
    assert per_epoch_lido_midterm_penalties[EpochNumber(14096)] == {
        '0x0': 1000000000, '0x1': 1000000000, '0x2': 1000000000
    }


@pytest.mark.unit
def test_get_per_frame_lido_midterm_penalties():
    lido_slashed_validators = {
        '0x0': all_slashed_validators['0x0'],
        '0x1': all_slashed_validators['0x1'],
        '0x2': all_slashed_validators['0x2']
    }
    total_balance = 32 * 60000 * 10 ** 9
    per_epoch_buckets = MidtermSlashingPenalty.get_per_epoch_buckets(all_slashed_validators, EpochNumber(15000))
    per_epoch_lido_midterm_penalties = MidtermSlashingPenalty.get_per_epoch_lido_midterm_penalties(
       per_epoch_buckets, lido_slashed_validators, total_balance
    )

    per_frame_lido_midterm_penalties = MidtermSlashingPenalty.get_per_frame_lido_midterm_penalties(
        per_epoch_lido_midterm_penalties,
        FrameConfig(
            initial_epoch=EpochNumber(0),
            epochs_per_frame=EpochNumber(225),
            fast_lane_length_slots=0,
        )
    )

    assert len(per_frame_lido_midterm_penalties) == 1
    assert per_frame_lido_midterm_penalties[0] == 3000000000


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
        fast_lane_length_slots=0,
    )
    frame_by_epoch = MidtermSlashingPenalty.get_frame_by_epoch(epoch, frame_config)
    assert frame_by_epoch == expected_frame
