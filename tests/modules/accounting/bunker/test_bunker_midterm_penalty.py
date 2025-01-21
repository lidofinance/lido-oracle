from unittest.mock import Mock

import pytest

from src.constants import MAX_EFFECTIVE_BALANCE_ELECTRA, MAX_EFFECTIVE_BALANCE
from src.modules.submodules.consensus import FrameConfig
from src.modules.submodules.types import ChainConfig
from src.providers.consensus.types import Validator, ValidatorStatus, ValidatorState
from src.services.bunker_cases.midterm_slashing_penalty import MidtermSlashingPenalty
from src.types import EpochNumber, ReferenceBlockStamp, Gwei
from src.utils.web3converter import Web3Converter


def simple_blockstamp(
    block_number: int,
) -> ReferenceBlockStamp:
    return ReferenceBlockStamp(f"0x{block_number}", block_number, '', block_number, 0, block_number, block_number // 32)


def simple_validators(
    from_index: int,
    to_index: int,
    slashed=False,
    withdrawable_epoch="8192",
    exit_epoch="7892",
    effective_balance=str(32 * 10**9),
) -> list[Validator]:
    validators = []
    for index in range(from_index, to_index + 1):
        validator = Validator(
            index=str(index),
            balance=effective_balance,
            validator=ValidatorState(
                pubkey=f"0x{index}",
                withdrawal_credentials='',
                effective_balance=effective_balance,
                slashed=slashed,
                activation_eligibility_epoch='',
                activation_epoch='0',
                exit_epoch=exit_epoch,
                withdrawable_epoch=withdrawable_epoch,
            ),
        )
        validators.append(validator)
    return validators


TEST_ELECTRA_FORK_EPOCH = 450


@pytest.fixture(params=[TEST_ELECTRA_FORK_EPOCH])
def spec_with_electra(request):
    # sets the electra fork epoch to the test value for calculating the penalty
    return Mock(ELECTRA_FORK_EPOCH=request.param)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("blockstamp", "all_validators", "lido_validators", "report_cl_rebase", "expected_result"),
    [
        (
            # no one slashed
            simple_blockstamp(0),
            simple_validators(0, 50),
            simple_validators(0, 9),
            0,
            False,
        ),
        (
            # no one Lido slashed
            simple_blockstamp(0),
            [*simple_validators(0, 49), *simple_validators(50, 99, slashed=True)],
            simple_validators(0, 9),
            0,
            False,
        ),
        (
            # Lido slashed, but midterm penalty is not in the future
            simple_blockstamp(1500000),
            [
                *simple_validators(0, 49),
                *simple_validators(50, 99, slashed=True, exit_epoch="16084", withdrawable_epoch="16384"),
            ],
            simple_validators(50, 99, slashed=True, exit_epoch="16084", withdrawable_epoch="16384"),
            0,
            False,
        ),
        (
            # one day since last report, penalty greater than report rebase
            simple_blockstamp(225 * 32),
            [*simple_validators(0, 49), *simple_validators(50, 99, slashed=True)],
            simple_validators(50, 99, slashed=True),
            49 * 32 * 10**9,
            True,
        ),
        (
            # three days since last report, penalty greater than frame rebase
            simple_blockstamp(3 * 225 * 32),
            [*simple_validators(0, 49), *simple_validators(50, 99, slashed=True)],
            simple_validators(50, 99, slashed=True),
            3 * 49 * 32 * 10**9,
            True,
        ),
        (
            # one day since last report,penalty equal report rebase
            simple_blockstamp(225 * 32),
            [*simple_validators(0, 49), *simple_validators(50, 99, slashed=True)],
            simple_validators(50, 99, slashed=True),
            50 * 32 * 10**9,
            False,
        ),
        (
            # one day since last report, penalty less report rebase
            simple_blockstamp(225 * 32),
            [*simple_validators(0, 49), *simple_validators(50, 99, slashed=True)],
            simple_validators(50, 99, slashed=True),
            51 * 32 * 10**9,
            False,
        ),
    ],
)
def test_is_high_midterm_slashing_penalty_pre_electra(
    blockstamp, all_validators, lido_validators, report_cl_rebase, expected_result
):
    cl_spec = Mock()
    chain_config = ChainConfig(
        slots_per_epoch=32,
        seconds_per_slot=12,
        genesis_time=0,
    )
    frame_config = FrameConfig(
        initial_epoch=EpochNumber(0),
        epochs_per_frame=EpochNumber(225),
        fast_lane_length_slots=0,
    )
    web3_converter = Web3Converter(chain_config, frame_config)

    result = MidtermSlashingPenalty.is_high_midterm_slashing_penalty(
        blockstamp, 2, cl_spec, web3_converter, all_validators, lido_validators, report_cl_rebase, 0
    )
    assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    ("blockstamp", "all_validators", "lido_validators", "report_cl_rebase", "expected_result"),
    [
        (
            # no one slashed
            simple_blockstamp(0),
            simple_validators(0, 50),
            simple_validators(0, 9),
            0,
            False,
        ),
        (
            # no one Lido slashed
            simple_blockstamp(0),
            [*simple_validators(0, 49), *simple_validators(50, 99, slashed=True)],
            simple_validators(0, 9),
            0,
            False,
        ),
        (
            # Lido slashed, but midterm penalty is not in the future
            simple_blockstamp(1500000),
            [
                *simple_validators(0, 49),
                *simple_validators(50, 99, slashed=True, exit_epoch="16084", withdrawable_epoch="16384"),
            ],
            simple_validators(50, 99, slashed=True, exit_epoch="16084", withdrawable_epoch="16384"),
            0,
            False,
        ),
        (
            # one day since last report, penalty greater than report rebase
            simple_blockstamp(225 * 32),
            [*simple_validators(0, 49), *simple_validators(50, 99, slashed=True)],
            simple_validators(50, 99, slashed=True),
            49 * 32 * 10**9,
            True,
        ),
        (
            # three days since last report, penalty greater than frame rebase
            simple_blockstamp(3 * 225 * 32),
            [*simple_validators(0, 49), *simple_validators(50, 99, slashed=True)],
            simple_validators(50, 99, slashed=True),
            3 * 49 * 32 * 10**9,
            True,
        ),
        (
            # one day since last report,penalty equal report rebase
            simple_blockstamp(225 * 32),
            [*simple_validators(0, 49), *simple_validators(50, 99, slashed=True)],
            simple_validators(50, 99, slashed=True),
            50 * 32 * 10**9,
            False,
        ),
        (
            # one day since last report, penalty less report rebase
            simple_blockstamp(225 * 32),
            [*simple_validators(0, 49), *simple_validators(50, 99, slashed=True)],
            simple_validators(50, 99, slashed=True),
            51 * 32 * 10**9,
            False,
        ),
    ],
)
def test_is_high_midterm_slashing_penalty_post_electra(
    blockstamp, spec_with_electra, all_validators, lido_validators, report_cl_rebase, expected_result
):
    chain_config = ChainConfig(
        slots_per_epoch=32,
        seconds_per_slot=12,
        genesis_time=0,
    )
    frame_config = FrameConfig(
        initial_epoch=EpochNumber(0),
        epochs_per_frame=EpochNumber(225),
        fast_lane_length_slots=0,
    )
    web3_converter = Web3Converter(chain_config, frame_config)
    result = MidtermSlashingPenalty.is_high_midterm_slashing_penalty(
        blockstamp,
        3,
        spec_with_electra,
        web3_converter,
        all_validators,
        lido_validators,
        report_cl_rebase,
        0,
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
            [8192],
        ),
        # slashing epoch is not determined
        (
            simple_validators(0, 0, slashed=True, exit_epoch="16380", withdrawable_epoch="16384")[0],
            EpochNumber(225),
            list(range(226)),
        ),
        # slashing epoch is not determined and ref epoch is not last epoch in first frame
        (
            simple_validators(0, 0, slashed=True, exit_epoch="16380", withdrawable_epoch="16384")[0],
            EpochNumber(16000),
            list(range(7808, 8193)),
        ),
    ],
)
def test_get_possible_slashed_epochs(validator, spec_with_electra, ref_epoch, expected_result):
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
            {(18, 4049): simple_validators(0, 9, slashed=True)},
        ),
        (
            # midterm frames in past
            100500,
            simple_validators(0, 9, slashed=True),
            {},
        ),
        (
            # different midterm epochs in different frames
            225,
            [
                *simple_validators(0, 9, slashed=True),
                *simple_validators(10, 59, slashed=True, withdrawable_epoch="8417"),
            ],
            {
                (18, 4049): simple_validators(0, 9, slashed=True),
                (19, 4274): simple_validators(10, 59, slashed=True, withdrawable_epoch="8417"),
            },
        ),
    ],
)
def test_get_per_frame_lido_validators_with_future_midterm_epoch(
    ref_epoch, spec_with_electra, future_midterm_penalty_lido_slashed_validators, expected_result
):
    chain_config = ChainConfig(
        slots_per_epoch=32,
        seconds_per_slot=12,
        genesis_time=0,
    )
    frame_config = FrameConfig(
        initial_epoch=EpochNumber(0),
        epochs_per_frame=EpochNumber(225),
        fast_lane_length_slots=0,
    )
    web3_converter = Web3Converter(chain_config, frame_config)

    result = MidtermSlashingPenalty.get_lido_validators_with_future_midterm_epoch(
        EpochNumber(ref_epoch),
        web3_converter,
        future_midterm_penalty_lido_slashed_validators,
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
            {(18, 4050): simple_validators(0, 0, slashed=True)},
            simple_validators(0, 0, slashed=True),
            100,
            {18: 0},
        ),
        (
            # all are slashed
            225,
            {(18, 4050): simple_validators(0, 99, slashed=True)},
            simple_validators(0, 99, slashed=True),
            100,
            {18: 100 * 32 * 10**9},
        ),
        (
            # slashed in different frames with determined slashing epochs
            225,
            {
                (18, 4050): simple_validators(0, 9, slashed=True),
                (19, 4725): simple_validators(10, 59, slashed=True, exit_epoch="8000", withdrawable_epoch="8417"),
            },
            [
                *simple_validators(0, 9, slashed=True),
                *simple_validators(10, 59, slashed=True, exit_epoch="8000", withdrawable_epoch="8417"),
            ],
            100,
            {18: 10 * 32 * 10**9, 19: 50 * 32 * 10**9},
        ),
        (
            # slashed in different epochs in different frames without determined shasling epochs
            225,
            {
                (18, 4050): [
                    *simple_validators(0, 5),
                    *simple_validators(6, 9, slashed=True, exit_epoch="8192", withdrawable_epoch="8197"),
                ],
                (19, 4725): [
                    *simple_validators(10, 29, slashed=True, exit_epoch="8000", withdrawable_epoch="8417"),
                    *simple_validators(30, 59, slashed=True, exit_epoch="8417", withdrawable_epoch="8419"),
                ],
            },
            [
                *simple_validators(0, 5),
                *simple_validators(6, 9, slashed=True, exit_epoch="8192", withdrawable_epoch="8197"),
                *simple_validators(10, 29, slashed=True, exit_epoch="8000", withdrawable_epoch="8417"),
                *simple_validators(30, 59, slashed=True, exit_epoch="8417", withdrawable_epoch="8419"),
            ],
            100,
            {18: 10 * 32 * 10**9, 19: 50 * 32 * 10**9},
        ),
    ],
)
def test_get_future_midterm_penalty_sum_in_frames_pre_electra(
    ref_epoch, per_frame_validators, all_slashed_validators, active_validators_count, expected_result
):
    result = MidtermSlashingPenalty.get_future_midterm_penalty_sum_in_frames_pre_electra(
        EpochNumber(ref_epoch), all_slashed_validators, active_validators_count * 32 * 10**9, per_frame_validators
    )

    assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    (
        "ref_epoch",
        "spec_with_electra",
        "per_frame_validators",
        "all_slashed_validators",
        "active_validators_count",
        "expected_result",
    ),
    [
        (225, 225, {}, [], 50000, {}),
        (
            # one is slashed before electra
            225,
            4500,
            {(18, 4049): simple_validators(0, 0, slashed=True)},
            simple_validators(0, 0, slashed=True),
            50000,
            {18: 0},
        ),
        (
            # one is slashed after electra
            225,
            225,
            {(18, 4049): simple_validators(0, 0, slashed=True)},
            simple_validators(0, 0, slashed=True),
            50000,
            {18: 1_920_000},
        ),
        (
            # all are slashed before electra
            225,
            4500,
            {(18, 4049): simple_validators(0, 99, slashed=True)},
            simple_validators(0, 99, slashed=True),
            50000,
            {18: 0},
        ),
        (
            # all are slashed after electra
            225,
            225,
            {(18, 4049): simple_validators(0, 99, slashed=True)},
            simple_validators(0, 99, slashed=True),
            50000,
            {18: 19_200_000_000},
        ),
        (
            # slashed in different frames with determined slashing epochs in different forks
            225,
            4500,
            {
                (18, 4049): simple_validators(0, 0, slashed=True),
                (19, 4724): simple_validators(10, 59, slashed=True, exit_epoch="8000", withdrawable_epoch="8417"),
            },
            [
                *simple_validators(0, 0, slashed=True),
                *simple_validators(10, 59, slashed=True, exit_epoch="8000", withdrawable_epoch="8417"),
            ],
            50000,
            {18: 0, 19: 4_896_000_000},
        ),
        (
            # slashed in different epochs in different frames without determined slashing epochs in different forks
            225,
            4500,
            {
                (18, 4049): [
                    *simple_validators(0, 5),
                    *simple_validators(6, 9, slashed=True, exit_epoch="8192", withdrawable_epoch="8197"),
                ],
                (19, 4724): [
                    *simple_validators(10, 29, slashed=True, exit_epoch="8000", withdrawable_epoch="8417"),
                    *simple_validators(30, 59, slashed=True, exit_epoch="8417", withdrawable_epoch="8419"),
                ],
            },
            [
                *simple_validators(0, 5),
                *simple_validators(6, 9, slashed=True, exit_epoch="8192", withdrawable_epoch="8197"),
                *simple_validators(10, 29, slashed=True, exit_epoch="8000", withdrawable_epoch="8417"),
                *simple_validators(30, 59, slashed=True, exit_epoch="8417", withdrawable_epoch="8419"),
            ],
            50000,
            {18: 0, 19: 5_760_000_000},
        ),
    ],
    indirect=["spec_with_electra"],
)
def test_get_future_midterm_penalty_sum_in_frames_post_electra(
    ref_epoch,
    spec_with_electra,
    per_frame_validators,
    all_slashed_validators,
    active_validators_count,
    expected_result,
):
    result = MidtermSlashingPenalty.get_future_midterm_penalty_sum_in_frames_post_electra(
        EpochNumber(ref_epoch),
        spec_with_electra,
        all_slashed_validators,
        active_validators_count * 32 * 10**9,
        per_frame_validators,
    )

    assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    ("ref_epoch", "all_slashed_validators", "total_balance", "validators_in_frame", "expected_result"),
    [
        (225, [], 100 * 32 * 10**9, [], 0),
        (
            # one is slashed
            225,
            simple_validators(0, 0, slashed=True),
            100 * 32 * 10**9,
            simple_validators(0, 0, slashed=True),
            0,
        ),
        (
            # all are slashed
            225,
            simple_validators(0, 99, slashed=True),
            100 * 32 * 10**9,
            simple_validators(0, 99, slashed=True),
            100 * 32 * 10**9,
        ),
        (
            # several are slashed
            225,
            simple_validators(0, 9, slashed=True),
            100 * 32 * 10**9,
            simple_validators(0, 9, slashed=True),
            10 * 9 * 10**9,
        ),
        (
            # slashed in different epochs in different frames without determined slashing epochs
            225,
            [
                *simple_validators(0, 5, slashed=True),
                *simple_validators(6, 9, slashed=True, exit_epoch="8192", withdrawable_epoch="8197"),
            ],
            100 * 32 * 10**9,
            [
                *simple_validators(0, 5, slashed=True),
                *simple_validators(6, 9, slashed=True, exit_epoch="8192", withdrawable_epoch="8197"),
            ],
            10 * 9 * 10**9,
        ),
    ],
)
def test_predict_midterm_penalty_in_frame_pre_electra(
    ref_epoch, all_slashed_validators, total_balance, validators_in_frame, expected_result
):
    result = MidtermSlashingPenalty.predict_midterm_penalty_in_frame_pre_electra(
        EpochNumber(ref_epoch), all_slashed_validators, total_balance, validators_in_frame
    )

    assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    (
        "ref_epoch",
        "is_after_electra",
        "all_slashed_validators",
        "total_balance",
        "validators_in_frame",
        "expected_result",
    ),
    [
        # BEFORE ELECTRA
        (225, False, [], 100 * 32 * 10**9, [], 0),
        (
            # one is slashed
            225,
            False,
            simple_validators(0, 0, slashed=True),
            100 * 32 * 10**9,
            simple_validators(0, 0, slashed=True),
            0,
        ),
        (
            # all are slashed
            225,
            False,
            simple_validators(0, 99, slashed=True),
            100 * 32 * 10**9,
            simple_validators(0, 99, slashed=True),
            100 * 32 * 10**9,
        ),
        (
            # several are slashed
            225,
            False,
            simple_validators(0, 9, slashed=True),
            100 * 32 * 10**9,
            simple_validators(0, 9, slashed=True),
            10 * 9 * 10**9,
        ),
        (
            # slashed in different epochs in different frames without determined slashing epochs
            225,
            False,
            [
                *simple_validators(0, 5, slashed=True),
                *simple_validators(6, 9, slashed=True, exit_epoch="8192", withdrawable_epoch="8197"),
            ],
            100 * 32 * 10**9,
            [
                *simple_validators(0, 5, slashed=True),
                *simple_validators(6, 9, slashed=True, exit_epoch="8192", withdrawable_epoch="8197"),
            ],
            10 * 9 * 10**9,
        ),
        # AFTER ELECTRA
        (225, True, [], 100 * 32 * 10**9, [], 0),
        (
            # one is slashed
            225,
            True,
            simple_validators(0, 0, slashed=True),
            100 * 32 * 10**9,
            simple_validators(0, 0, slashed=True),
            960_000_000,
        ),
        (
            # all are slashed
            225,
            True,
            simple_validators(0, 99, slashed=True),
            100 * 32 * 10**9,
            simple_validators(0, 99, slashed=True),
            100 * 32 * 10**9,
        ),
        (
            # several are slashed
            225,
            True,
            simple_validators(0, 9, slashed=True),
            100 * 32 * 10**9,
            simple_validators(0, 9, slashed=True),
            96_000_000_000,
        ),
        (
            # slashed in different epochs in different frames without determined slashing epochs
            225,
            True,
            [
                *simple_validators(0, 5, slashed=True),
                *simple_validators(6, 9, slashed=True, exit_epoch="8192", withdrawable_epoch="8197"),
            ],
            100 * 32 * 10**9,
            [
                *simple_validators(0, 5, slashed=True),
                *simple_validators(6, 9, slashed=True, exit_epoch="8192", withdrawable_epoch="8197"),
            ],
            96_000_000_000,
        ),
    ],
)
def test_predict_midterm_penalty_in_frame_post_electra(
    ref_epoch,
    is_after_electra,
    all_slashed_validators,
    total_balance,
    validators_in_frame,
    expected_result,
    spec_with_electra,
):
    result = MidtermSlashingPenalty.predict_midterm_penalty_in_frame_post_electra(
        report_ref_epoch=EpochNumber(ref_epoch),
        frame_ref_epoch=EpochNumber(
            spec_with_electra.ELECTRA_FORK_EPOCH if is_after_electra else spec_with_electra.ELECTRA_FORK_EPOCH - 1
        ),
        cl_spec=spec_with_electra,
        all_slashed_validators=all_slashed_validators,
        total_balance=total_balance,
        midterm_penalized_validators_in_frame=validators_in_frame,
    )

    assert result == expected_result


# 50% active validators with 2048 EB and the rest part with 32 EB
half_electra = [
    *simple_validators(0, 250_000, effective_balance=str(MAX_EFFECTIVE_BALANCE)),
    *simple_validators(250_001, 500_000, effective_balance=str(MAX_EFFECTIVE_BALANCE_ELECTRA)),
]
# 20% active validators with 2048 EB and the rest part with 32 EB
part_electra = [
    *simple_validators(0, 10_000, effective_balance=str(MAX_EFFECTIVE_BALANCE_ELECTRA)),
    *simple_validators(10_001, 500_000, effective_balance=str(MAX_EFFECTIVE_BALANCE)),
]

one_32eth = simple_validators(0, 0, effective_balance=str(MAX_EFFECTIVE_BALANCE))
one_2048eth = simple_validators(0, 0, effective_balance=str(MAX_EFFECTIVE_BALANCE_ELECTRA))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("bounded_slashed_validators", "active_validators", "expected_penalty"),
    [
        (one_32eth, half_electra, 5888),
        (one_2048eth, half_electra, 378_080),
        (one_32eth, part_electra, 84_928),
        (one_2048eth, part_electra, 5_436_832),
        (100 * one_32eth, half_electra, 590_752),
        (100 * one_2048eth, half_electra, 37_809_216),
        (100 * one_32eth, part_electra, 8_495_072),
        (100 * one_2048eth, part_electra, 543_686_016),
        (10_000 * one_32eth, half_electra, 59_076_896),
        (10_000 * one_2048eth, half_electra, 3_780_922_816),
        (10_000 * one_32eth, part_electra, 849_509_408),
        (10_000 * one_2048eth, part_electra, 32_000_000_000),
    ],
    ids=[
        "1 bounded slashing with 32 EB, half active validators with 2048 EB and the rest part with 32 EB",
        "1 bounded slashing with 2048 EB, half active validators with 2048 EB and the rest part with 32 EB",
        "1 bounded slashing with 32 EB, 10% active validators with 2048 EB and the rest part with 32 EB",
        "1 bounded slashing with 2048 EB, 10% active validators with 2048 EB and the rest part with 32 EB",
        "100 bounded slashing with 32 EB, half active validators with 2048 EB and the rest part with 32 EB",
        "100 bounded slashing with 2048 EB, half active validators with 2048 EB and the rest part with 32 EB",
        "100 bounded slashing with 32 EB, 10% active validators with 2048 EB and the rest part with 32 EB",
        "100 bounded slashing with 2048 EB, 10% active validators with 2048 EB and the rest part with 32 EB",
        "10_000 bounded slashing with 32 EB, half active validators with 2048 EB and the rest part with 32 EB",
        "10_000 bounded slashing with 2048 EB, half active validators with 2048 EB and the rest part with 32 EB",
        "10_000 bounded slashing with 32 EB, 10% active validators with 2048 EB and the rest part with 32 EB",
        "10_000 bounded slashing with 2048 EB, 10% active validators with 2048 EB and the rest part with 32 EB",
    ],
)
def test_get_validator_midterm_penalty_electra(bounded_slashed_validators, active_validators, expected_penalty):
    result = MidtermSlashingPenalty.get_validator_midterm_penalty_electra(
        validator=simple_validators(0, 0)[0],
        bound_slashed_validators=bounded_slashed_validators,
        total_balance=Gwei(sum(int(v.validator.effective_balance) for v in active_validators)),
    )

    assert result == expected_penalty


@pytest.mark.unit
@pytest.mark.parametrize(
    ("bounded_slashings_count", "active_validators_count", "expected_penalty"),
    [
        (1, 500000, 0),
        (100, 500000, 0),
        (1000, 500000, 0),
        (5000, 500000, 0),
        (10000, 500000, 1000000000),
        (20000, 500000, 3000000000),
        (50000, 500000, 9000000000),
    ],
)
def test_get_validator_midterm_penalty(bounded_slashings_count, active_validators_count, expected_penalty):
    result = MidtermSlashingPenalty.get_validator_midterm_penalty(
        simple_validators(0, 0)[0], bounded_slashings_count, active_validators_count * 32 * 10**9
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
            simple_validators(0, 0, exit_epoch="16380", withdrawable_epoch="16384"),
            12288,
            simple_validators(0, 0, exit_epoch="16380", withdrawable_epoch="16384"),
        ),
    ],
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
            0,
        ),
        (
            # slashed and withdrawable epoch greater than ref_epoch
            simple_validators(0, 9, slashed=True),
            EpochNumber(0),
            10,
        ),
        (
            # slashed and withdrawable epoch less than ref_epoch
            simple_validators(0, 9, slashed=True),
            EpochNumber(20000000),
            0,
        ),
    ],
)
def test_get_slashed_validators_with_impact_to_midterm_penalties(lido_validators, ref_epoch, expected_len):
    result = MidtermSlashingPenalty.get_slashed_validators_with_impact_on_midterm_penalties(lido_validators, ref_epoch)
    assert len(result) == expected_len


@pytest.mark.unit
@pytest.mark.parametrize(
    ("report_cl_rebase", "blockstamp", "last_report_ref_slot", "expected_result"),
    [
        (5 * 32 * 10**9, simple_blockstamp(225 * 32), 0, 5 * 32 * 10**9),
        (7 * 5 * 32 * 10**9, simple_blockstamp(7 * 225 * 32), 0, 5 * 32 * 10**9),
    ],
)
def test_get_frame_cl_rebase_from_report_cl_rebase(report_cl_rebase, blockstamp, last_report_ref_slot, expected_result):
    chain_config = ChainConfig(
        slots_per_epoch=32,
        seconds_per_slot=12,
        genesis_time=0,
    )
    frame_config = FrameConfig(
        initial_epoch=EpochNumber(0),
        epochs_per_frame=EpochNumber(225),
        fast_lane_length_slots=0,
    )
    web3_converter = Web3Converter(chain_config, frame_config)
    result = MidtermSlashingPenalty.get_frame_cl_rebase_from_report_cl_rebase(
        web3_converter, report_cl_rebase, blockstamp, last_report_ref_slot
    )

    assert result == expected_result


@pytest.mark.unit
def test_get_midterm_slashing_epoch():
    result = MidtermSlashingPenalty.get_midterm_penalty_epoch(simple_validators(0, 0)[0])
    assert result == 4096
