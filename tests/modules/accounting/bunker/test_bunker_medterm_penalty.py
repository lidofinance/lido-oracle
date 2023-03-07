import pytest

from src.modules.submodules.consensus import FrameConfig
from src.providers.consensus.typings import Validator, ValidatorStatus, ValidatorState
from src.services.bunker_cases.midterm_slashing_penalty import MidtermSlashingPenalty
from src.typings import EpochNumber, ReferenceBlockStamp


def simple_blockstamp(block_number: int,) -> ReferenceBlockStamp:
    return ReferenceBlockStamp(
        '', f"0x{block_number}", block_number, '', block_number, 0, block_number, block_number // 32
    )


def simple_validators(
    from_index: int, to_index: int, stashed=False, withdrawable_epoch="8192", exit_epoch="7892"
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
                slashed=stashed,
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
            {v.validator.pubkey: v for v in simple_validators(0, 50)},
            {v.validator.pubkey: v for v in simple_validators(0, 9)},
            0,
            False
        ),
        (
            # no one Lido slashed
            simple_blockstamp(0),
            {
                **{v.validator.pubkey: v for v in simple_validators(0, 49)},
                **{v.validator.pubkey: v for v in simple_validators(50, 99, stashed=True)}
            },
            {v.validator.pubkey: v for v in simple_validators(0, 9)},
            0,
            False
        ),
        (
            # Lido slashed, but midterm penalty is not in the future
            simple_blockstamp(1500000),
            {
                **{v.validator.pubkey: v for v in simple_validators(0, 49)},
                **{v.validator.pubkey: v for v in simple_validators(50, 99, stashed=True, exit_epoch="16084", withdrawable_epoch="16384")}
            },
            {v.validator.pubkey: v for v in simple_validators(50, 99, stashed=True, exit_epoch="16084", withdrawable_epoch="16384")},
            0,
            False
        ),
        (
            # penalty greater than rebase
            simple_blockstamp(0),
            {
                **{v.validator.pubkey: v for v in simple_validators(0, 49)},
                **{v.validator.pubkey: v for v in simple_validators(50, 99, stashed=True)}
            },
            {v.validator.pubkey: v for v in simple_validators(50, 99, stashed=True)},
            49 * 32 * 10 ** 9,
            True
        ),
        (
            # penalty equal rebase
            simple_blockstamp(0),
            {
                **{v.validator.pubkey: v for v in simple_validators(0, 49)},
                **{v.validator.pubkey: v for v in simple_validators(50, 99, stashed=True)}
            },
            {v.validator.pubkey: v for v in simple_validators(50, 99, stashed=True)},
            50 * 32 * 10 ** 9,
            False
        ),
        (
            # penalty less rebase
            simple_blockstamp(0),
            {
                **{v.validator.pubkey: v for v in simple_validators(0, 49)},
                **{v.validator.pubkey: v for v in simple_validators(50, 99, stashed=True)}
            },
            {v.validator.pubkey: v for v in simple_validators(50, 99, stashed=True)},
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
    ("all_slashed_validators", "ref_epoch", "expected_result"),
    [
        (
            # slashing epoch is determined
            {v.validator.pubkey: v for v in simple_validators(0, 9)},
            EpochNumber(225),
            {0: {v.validator.pubkey: v for v in simple_validators(0, 9)}}
        ),
        (
            # slashing epoch is not determined
            {
                v.validator.pubkey: v
                for v in simple_validators(0, 0, exit_epoch="16380", withdrawable_epoch="16384")
            },
            EpochNumber(16000),
            {
                epoch: {
                    v.validator.pubkey: v
                    for v in simple_validators(0, 0, exit_epoch="16380", withdrawable_epoch="16384")}
                for epoch in range(7808, 8193)
            }
        ),
    ]
)
def test_get_per_possible_slashed_epoch_buckets(all_slashed_validators, ref_epoch, expected_result):

    result = MidtermSlashingPenalty.get_per_possible_slashed_epoch_buckets(all_slashed_validators, ref_epoch)

    assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    ("validator", "ref_epoch", "expected_result"),
    [
        # slashing epoch is first epoch and it's determined
        (simple_validators(0, 0)[0], EpochNumber(225), [0]),
        # slashing epoch is not first epoch and it's determined
        (simple_validators(0, 0, exit_epoch="16084", withdrawable_epoch="16384")[0], EpochNumber(225), [8192]),
        # slashing epoch is not determined
        (
                simple_validators(0, 0, exit_epoch="16380", withdrawable_epoch="16384")[0],
                EpochNumber(225),
                list(range(8193))
        ),
        # slashing epoch is not determined and ref epoch is not last epoch in first frame
        (
                simple_validators(0, 0, exit_epoch="16380", withdrawable_epoch="16384")[0],
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
    ("future_midterm_penalty_lido_slashed_validators", "expected_result"),
    [
        ({}, {}),
        (
            # the same midterm epoch
            {v.validator.pubkey: v for v in simple_validators(0, 9)},
            {18: {4096: simple_validators(0, 9)}}
        ),
        (
            # different midterm epochs in different frames
            {
                **{v.validator.pubkey: v for v in simple_validators(0, 9)},
                **{v.validator.pubkey: v for v in simple_validators(10, 59, withdrawable_epoch="8417")}
            },
            {
                18: {4096: simple_validators(0, 9)},
                19: {4321: simple_validators(10, 59, withdrawable_epoch="8417")}
            }
        ),
    ]
)
def test_get_per_frame_lido_validators_with_future_midterm_epoch(
    future_midterm_penalty_lido_slashed_validators, expected_result
):
    frame_config = FrameConfig(
        initial_epoch=EpochNumber(0),
        epochs_per_frame=EpochNumber(225),
        fast_lane_length_slots=0,
    )

    result = MidtermSlashingPenalty.get_per_frame_lido_validators_with_future_midterm_epoch(
        future_midterm_penalty_lido_slashed_validators, frame_config
    )

    assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    ("per_frame_validators", "per_slashing_epoch_buckets", "active_validators_count", "expected_result"),
    [
        ({}, {}, 100, {}),
        (
            # one is slashed
            {18: {4096: simple_validators(0, 0)}},
            {0: {"0x0": simple_validators(0, 0)[0]}},
            100,
            {18: 0}
        ),
        (
            # all are slashed
            {18: {4096: simple_validators(0, 99)}},
            {0: {v.validator.pubkey: v for v in simple_validators(0, 99)}},
            100,
            {18: 100 * 32 * 10 ** 9}
        ),
        (
            # slashed in the same epoch in different frames
            {
                18: {4096: simple_validators(0, 9)},
                19: {4321: simple_validators(10, 59)}},
            {
                0: {v.validator.pubkey: v for v in simple_validators(0, 9)},
                225: {v.validator.pubkey: v for v in simple_validators(10, 59)}
            },
            100,
            {18: 10 * 32 * 10 ** 9, 19: 50 * 32 * 10 ** 9}
        ),
        (
            # slashed in different epochs in different frames
            {
                18: {
                    4096: simple_validators(0, 5),
                    4106: simple_validators(6, 9)
                },
                19: {
                    4321: simple_validators(10, 29),
                    4330: simple_validators(30, 59),
                }
            },
            {
                0: {v.validator.pubkey: v for v in simple_validators(0, 5)},
                5: {v.validator.pubkey: v for v in simple_validators(6, 9)},
                10: {v.validator.pubkey: v for v in simple_validators(6, 9)},
                225: {v.validator.pubkey: v for v in simple_validators(10, 29)},
                227: {v.validator.pubkey: v for v in simple_validators(30, 59)},
                234: {v.validator.pubkey: v for v in simple_validators(30, 59)}
            },
            100,
            {18: 10 * 32 * 10 ** 9, 19: 50 * 32 * 10 ** 9}
        ),
    ]
)
def test_get_future_midterm_penalty_sum_in_frames(
    per_frame_validators, per_slashing_epoch_buckets, active_validators_count, expected_result
):

    result = MidtermSlashingPenalty.get_future_midterm_penalty_sum_in_frames(
        per_frame_validators, per_slashing_epoch_buckets, active_validators_count * 32 * 10 ** 9
    )

    assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    ("bound_slashed_validators_count", "active_validators_count", "expected_result"),
    [
        (1,  100, 96 * 10 ** 9),
        (3,  100, 3 * 96 * 10 ** 9),
        (33, 100, 33 * 96 * 10 ** 9),
        (50, 100, 100 * 32 * 10 ** 9),
    ]
)
def test_get_adjusted_total_slashing_balance(bound_slashed_validators_count, active_validators_count, expected_result):

    result = MidtermSlashingPenalty.get_adjusted_total_slashing_balance(
        bound_slashed_validators_count, active_validators_count * 32 * 10 ** 9
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

    result = MidtermSlashingPenalty.get_midterm_penalty(
        32 * 10 ** 9, bounded_slashings_count * 96 * 10 ** 9, active_validators_count * 32 * 10 ** 9
    )

    assert result == expected_penalty


@pytest.mark.unit
@pytest.mark.parametrize(
    ("per_slashing_epoch_buckets", "midterm_penalty_epoch", "expected_bounded"),
    [
        ({0: {"0x01": {}}}, 4096, {"0x01"}),
        ({0: {"0x01": {}}, 1: {"0x01": {}}}, 4096, {"0x01"}),
        ({4096: {"0x01": {}}}, 4096, {"0x01"}),
        ({4096: {"0x01": {}}}, 8192, {"0x01"}),
        ({4096: {"0x01": {}}}, 12288, {"0x01"}),
        ({4096: {"0x01": {}}}, 16384, set())
    ]
)
def test_get_bound_with_midterm_epoch_slashed_validators(per_slashing_epoch_buckets, midterm_penalty_epoch, expected_bounded):

    result = MidtermSlashingPenalty.get_bound_with_midterm_epoch_slashed_validators(
        per_slashing_epoch_buckets, midterm_penalty_epoch
    )

    assert set(result) == expected_bounded


@pytest.mark.unit
@pytest.mark.parametrize(
    ("lido_validators", "ref_epoch", "expected_len"),
    [
        (
            # no one slashed
            {v.validator.pubkey: v for v in simple_validators(0, 9)},
            EpochNumber(20000000),
            0
        ),
        (
            # slashed and withdrawable epoch greater than ref_epoch
            {v.validator.pubkey: v for v in simple_validators(0, 9, stashed=True)},
            EpochNumber(0),
            10
        ),
        (
            # slashed and withdrawable epoch less than ref_epoch
            {v.validator.pubkey: v for v in simple_validators(0, 9, stashed=True)},
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
            {v.validator.pubkey: v for v in simple_validators(0, 9, stashed=True)},
            EpochNumber(0),
            10
        ),
        (
            # slashed and withdrawable epoch less than ref_epoch
            {v.validator.pubkey: v for v in simple_validators(0, 9, stashed=True)},
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

