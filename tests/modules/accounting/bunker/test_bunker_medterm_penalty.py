import pytest

from src.modules.submodules.consensus import FrameConfig
from src.providers.consensus.typings import Validator, ValidatorStatus, ValidatorState
from src.services.bunker_cases.midterm_slashing_penalty import MidtermSlashingPenalty
from src.typings import EpochNumber, ReferenceBlockStamp


def simple_blockstamp(block_number: int,) -> ReferenceBlockStamp:
    return ReferenceBlockStamp(
        f"0x{block_number}", block_number, '', block_number, 0, block_number, block_number // 32
    )


def simple_validators(
    from_index: int, to_index: int, slashed=False, withdrawable_epoch="8192", exit_epoch="7892"
) -> list[Validator]:
    validators = []
    for index in range(from_index, to_index + 1):
        validator = Validator(
            index=str(index),
            balance=str(32 * 10 ** 9),
            status=ValidatorStatus.ACTIVE_ONGOING,
            validator=ValidatorState(
                pubkey=f"0x{index}",
                withdrawal_credentials='',
                effective_balance=str(32 * 10 ** 9),
                slashed=slashed,
                activation_eligibility_epoch='',
                activation_epoch='0',
                exit_epoch=exit_epoch,
                withdrawable_epoch=withdrawable_epoch,
            )
        )
        validators.append(validator)
    return validators


@pytest.mark.unit
@pytest.mark.parametrize(
    ("blockstamp", "all_validators", "lido_validators", "frame_cl_rebase", "expected_result"),
    [
        (
            # no one slashed
            simple_blockstamp(0),
            simple_validators(0, 50),
            simple_validators(0, 9),
            0,
            False
        ),
        (
            # no one Lido slashed
            simple_blockstamp(0),
            [*simple_validators(0, 49), *simple_validators(50, 99, slashed=True)],
            simple_validators(0, 9),
            0,
            False
        ),
        (
            # Lido slashed, but midterm penalty is not in the future
            simple_blockstamp(1500000),
            [
                *simple_validators(0, 49),
                *simple_validators(50, 99, slashed=True, exit_epoch="16084", withdrawable_epoch="16384")
            ],
            simple_validators(50, 99, slashed=True, exit_epoch="16084", withdrawable_epoch="16384"),
            0,
            False
        ),
        (
            # penalty greater than rebase
            simple_blockstamp(0),
            [
                *simple_validators(0, 49),
                *simple_validators(50, 99, slashed=True)
            ],
            simple_validators(50, 99, slashed=True),
            49 * 32 * 10 ** 9,
            True
        ),
        (
            # penalty equal rebase
            simple_blockstamp(0),
            [
                *simple_validators(0, 49),
                *simple_validators(50, 99, slashed=True)
            ],
            simple_validators(50, 99, slashed=True),
            50 * 32 * 10 ** 9,
            False
        ),
        (
            # penalty less rebase
            simple_blockstamp(0),
            [
                *simple_validators(0, 49),
                *simple_validators(50, 99, slashed=True)
            ],
            simple_validators(50, 99, slashed=True),
            51 * 32 * 10 ** 9,
            False
        )
    ]
)
def test_is_high_midterm_slashing_penalty(
    blockstamp,
    all_validators,
    lido_validators,
    frame_cl_rebase,
    expected_result
):
    frame_config = FrameConfig(
        initial_epoch=EpochNumber(0),
        epochs_per_frame=EpochNumber(225),
        fast_lane_length_slots=0,
    )

    result = MidtermSlashingPenalty.is_high_midterm_slashing_penalty(
        blockstamp, frame_config, all_validators, lido_validators, frame_cl_rebase
    )
    assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    ("validator", "ref_epoch", "expected_result"),
    [
        # slashing epoch is first epoch and it's determined
        (simple_validators(0, 0, slashed=True)[0], EpochNumber(225), [0]),
        # slashing epoch is not first epoch and it's determined
        (
            simple_validators(0, 0, slashed=True, exit_epoch="16084", withdrawable_epoch="16384")[0],
            EpochNumber(225),
            [8192]
        ),
        # slashing epoch is not determined
        (
            simple_validators(0, 0, slashed=True, exit_epoch="16380", withdrawable_epoch="16384")[0],
            EpochNumber(225),
            list(range(8193))
        ),
        # slashing epoch is not determined and ref epoch is not last epoch in first frame
        (
            simple_validators(0, 0, slashed=True, exit_epoch="16380", withdrawable_epoch="16384")[0],
            EpochNumber(16000),
            list(range(7808, 8193))
        ),
    ]
)
def test_get_possible_slashed_epochs(validator, ref_epoch, expected_result):

    result = MidtermSlashingPenalty.get_possible_slashed_epochs(validator, ref_epoch)

    assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    ("ref_epoch", "future_midterm_penalty_lido_slashed_validators", "expected_result"),
    [
        (225, {}, {}),
        (
            # the same midterm epoch
            225,
            simple_validators(0, 9, slashed=True),
            {18: simple_validators(0, 9, slashed=True)}
        ),
        (
            # midterm frames in past
            100500,
            simple_validators(0, 9, slashed=True),
            {}
        ),
        (
            # different midterm epochs in different frames
            225,
            [
                *simple_validators(0, 9, slashed=True),
                *simple_validators(10, 59, slashed=True, withdrawable_epoch="8417")
            ],
            {
                18: simple_validators(0, 9, slashed=True),
                19: simple_validators(10, 59, slashed=True, withdrawable_epoch="8417")
            }
        ),
    ]
)
def test_get_per_frame_lido_validators_with_future_midterm_epoch(
    ref_epoch, future_midterm_penalty_lido_slashed_validators, expected_result
):
    frame_config = FrameConfig(
        initial_epoch=EpochNumber(0),
        epochs_per_frame=EpochNumber(225),
        fast_lane_length_slots=0,
    )

    result = MidtermSlashingPenalty.get_per_frame_lido_validators_with_future_midterm_epoch(
        EpochNumber(ref_epoch), frame_config, future_midterm_penalty_lido_slashed_validators,
    )

    assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    ("ref_epoch", "per_frame_validators", "all_slashed_validators", "active_validators_count", "expected_result"),
    [
        (225, {}, [], 100, {}),
        (
            # one is slashed
            225,
            {18: simple_validators(0, 0, slashed=True)},
            simple_validators(0, 0, slashed=True),
            100,
            {18: 0}
        ),
        (
            # all are slashed
            225,
            {18: simple_validators(0, 99, slashed=True)},
            simple_validators(0, 99, slashed=True),
            100,
            {18: 100 * 32 * 10 ** 9}
        ),
        (
            # slashed in different frames with determined slashing epochs
            225,
            {
                18: simple_validators(0, 9, slashed=True),
                19: simple_validators(10, 59, slashed=True, exit_epoch="8000", withdrawable_epoch="8417"),
            },
            [
                *simple_validators(0, 9, slashed=True),
                *simple_validators(10, 59, slashed=True, exit_epoch="8000", withdrawable_epoch="8417")
            ],
            100,
            {18: 10 * 32 * 10 ** 9, 19: 50 * 32 * 10 ** 9}
        ),
        (
            # slashed in different epochs in different frames without determined shasling epochs
            225,
            {
                18: [
                    *simple_validators(0, 5),
                    *simple_validators(6, 9, slashed=True, exit_epoch="8192", withdrawable_epoch="8197")
                ],
                19: [
                    *simple_validators(10, 29, slashed=True, exit_epoch="8000", withdrawable_epoch="8417"),
                    *simple_validators(30, 59, slashed=True, exit_epoch="8417", withdrawable_epoch="8419"),
                ]
            },
            [
                *simple_validators(0, 5),
                *simple_validators(6, 9, slashed=True, exit_epoch="8192", withdrawable_epoch="8197"),
                *simple_validators(10, 29, slashed=True, exit_epoch="8000", withdrawable_epoch="8417"),
                *simple_validators(30, 59, slashed=True, exit_epoch="8417", withdrawable_epoch="8419")
            ],
            100,
            {18: 10 * 32 * 10 ** 9, 19: 50 * 32 * 10 ** 9}
        ),
    ]
)
def test_get_future_midterm_penalty_sum_in_frames(
    ref_epoch, per_frame_validators, all_slashed_validators, active_validators_count, expected_result
):

    result = MidtermSlashingPenalty.get_future_midterm_penalty_sum_in_frames(
        EpochNumber(ref_epoch), all_slashed_validators, active_validators_count * 32 * 10 ** 9, per_frame_validators
    )

    assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    ("ref_epoch", "all_slashed_validators", "total_balance", "validators_in_frame", "expected_result"),
    [
        (225, [], 100 * 32 * 10 ** 9, [], 0),
        (
            # one is slashed
            225,
            simple_validators(0, 0, slashed=True),
            100 * 32 * 10 ** 9,
            simple_validators(0, 0, slashed=True),
            0
        ),
        (
            # all are slashed
            225,
            simple_validators(0, 99, slashed=True),
            100 * 32 * 10 ** 9,
            simple_validators(0, 99, slashed=True),
            100 * 32 * 10 ** 9
        ),
        (
            # several are slashed
            225,
            simple_validators(0, 9, slashed=True),
            100 * 32 * 10 ** 9,
            simple_validators(0, 9, slashed=True),
            10 * 9 * 10 ** 9
        ),
        (
            # slashed in different epochs in different frames without determined slashing epochs
            225,
            [
                *simple_validators(0, 5, slashed=True),
                *simple_validators(6, 9, slashed=True, exit_epoch="8192", withdrawable_epoch="8197")
            ],
            100 * 32 * 10 ** 9,
            [
                *simple_validators(0, 5, slashed=True),
                *simple_validators(6, 9, slashed=True, exit_epoch="8192", withdrawable_epoch="8197"),
            ],
            10 * 9 * 10 ** 9
        ),
    ]
)
def test_predict_midterm_penalty_in_frame(
    ref_epoch, all_slashed_validators, total_balance, validators_in_frame, expected_result
):

    result = MidtermSlashingPenalty.predict_midterm_penalty_in_frame(
        EpochNumber(ref_epoch), all_slashed_validators, total_balance, validators_in_frame
    )

    assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    ("bounded_slashings_count", "active_validators_count", "expected_penalty"),
    [
        (1,    500000, 0),
        (100,  500000, 0),
        (1000, 500000, 0),
        (5000, 500000, 0),
        (10000, 500000, 1000000000),
        (20000, 500000, 3000000000),
        (50000, 500000, 9000000000),
    ]
)
def test_get_midterm_penalty(bounded_slashings_count, active_validators_count, expected_penalty):

    result = MidtermSlashingPenalty.get_validator_midterm_penalty(
        simple_validators(0,0)[0], bounded_slashings_count, active_validators_count * 32 * 10 ** 9
    )

    assert result == expected_penalty


@pytest.mark.unit
@pytest.mark.parametrize(
    ("ref_epoch", "slashed_validators", "midterm_penalty_epoch", "expected_bounded"),
    [
        (
            # slashing epoch is determined
            225,
            simple_validators(0, 9),
            4096,
            simple_validators(0, 9),
        ),
        (
            # slashing epoch is not determined
            EpochNumber(16000),
            simple_validators(0, 0, exit_epoch="16380", withdrawable_epoch="16384")
            ,
            12288,
            simple_validators(0, 0, exit_epoch="16380", withdrawable_epoch="16384")
        ),
    ]
)
def test_get_bound_with_midterm_epoch_slashed_validators(
    ref_epoch, slashed_validators, midterm_penalty_epoch, expected_bounded
):

    result = MidtermSlashingPenalty.get_bound_with_midterm_epoch_slashed_validators(
        EpochNumber(ref_epoch), slashed_validators, EpochNumber(midterm_penalty_epoch)
    )

    assert result == expected_bounded


@pytest.mark.unit
@pytest.mark.parametrize(
    ("lido_validators", "ref_epoch", "expected_len"),
    [
        (
            # no one slashed
            simple_validators(0, 9),
            EpochNumber(20000000),
            0
        ),
        (
            # slashed and withdrawable epoch greater than ref_epoch
            simple_validators(0, 9, slashed=True),
            EpochNumber(0),
            10
        ),
        (
            # slashed and withdrawable epoch less than ref_epoch
            simple_validators(0, 9, slashed=True),
            EpochNumber(20000000),
            0
        )
    ]
)
def test_get_not_withdrawn_slashed_validators(lido_validators, ref_epoch, expected_len):
    result = MidtermSlashingPenalty.get_not_withdrawn_slashed_validators(lido_validators, ref_epoch)
    assert len(result) == expected_len


@pytest.mark.unit
@pytest.mark.parametrize(
    ("slashed_validators", "ref_epoch", "expected_len"),
    [
        (
            # no one slashed
            {v.validator.pubkey: v for v in simple_validators(0, 9)},
            EpochNumber(20000000),
            0
        ),
        (
            # slashed and withdrawable epoch greater than ref_epoch
            {v.validator.pubkey: v for v in simple_validators(0, 9, slashed=True)},
            EpochNumber(0),
            10
        ),
        (
            # slashed and withdrawable epoch less than ref_epoch
            {v.validator.pubkey: v for v in simple_validators(0, 9, slashed=True)},
            EpochNumber(20000000),
            0
        )
    ]
)
def test_get_future_midterm_penalty_slashed_validators(slashed_validators, ref_epoch, expected_len):
    result = MidtermSlashingPenalty.get_future_midterm_penalty_slashed_validators(slashed_validators, ref_epoch)
    assert len(result) == expected_len


@pytest.mark.unit
@pytest.mark.parametrize(
    ("epoch", "expected_frame"),
    [
        (EpochNumber(0), 0),
        (EpochNumber(224), 0),
        (EpochNumber(225), 1),
        (EpochNumber(449), 1),
        (EpochNumber(450), 2)
    ]
)
def test_get_frame_by_epoch(epoch, expected_frame):
    frame_config = FrameConfig(
        initial_epoch=EpochNumber(0),
        epochs_per_frame=EpochNumber(225),
        fast_lane_length_slots=0,
    )
    frame_by_epoch = MidtermSlashingPenalty.get_frame_by_epoch(epoch, frame_config)
    assert frame_by_epoch == expected_frame


@pytest.mark.unit
def test_get_midterm_slashing_epoch():
    result = MidtermSlashingPenalty.get_midterm_slashing_epoch(simple_validators(0, 0)[0])
    assert result == 4096
