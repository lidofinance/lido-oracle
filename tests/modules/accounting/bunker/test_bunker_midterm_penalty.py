import pytest

from src.constants import (
    FAR_FUTURE_EPOCH,
    MAX_EFFECTIVE_BALANCE,
    MAX_EFFECTIVE_BALANCE_ELECTRA,
    EPOCHS_PER_SLASHINGS_VECTOR,
)
from src.modules.submodules.consensus import FrameConfig
from src.modules.submodules.types import ChainConfig
from src.providers.consensus.types import Validator, ValidatorState
from src.services.bunker_cases.midterm_slashing_penalty import MidtermSlashingPenalty
from src.types import EpochNumber, Gwei, ReferenceBlockStamp, SlotNumber, ValidatorIndex
from src.utils.web3converter import Web3Converter
from tests.factory.no_registry import ValidatorFactory, ValidatorStateFactory


def simple_blockstamp(
    block_number: int,
) -> ReferenceBlockStamp:
    return ReferenceBlockStamp(f"0x{block_number}", block_number, '', block_number, 0, block_number, block_number // 32)


def simple_validators(
    from_index: int,
    to_index: int,
    slashed=False,
    withdrawable_epoch=8192,
    exit_epoch=7892,
    effective_balance=Gwei(32 * 10**9),
) -> list[Validator]:
    validators = []
    for index in range(from_index, to_index + 1):
        validator = Validator(
            index=ValidatorIndex(index),
            balance=effective_balance,
            validator=ValidatorState(
                pubkey=f"0x{index}",
                withdrawal_credentials='',
                effective_balance=effective_balance,
                slashed=slashed,
                activation_eligibility_epoch=FAR_FUTURE_EPOCH,
                activation_epoch=EpochNumber(0),
                exit_epoch=EpochNumber(exit_epoch),
                withdrawable_epoch=EpochNumber(withdrawable_epoch),
            ),
        )
        validators.append(validator)
    return validators


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
            [*simple_validators(0, 999), *simple_validators(1000, 1049, slashed=True)],
            simple_validators(1000, 1049, slashed=True),
            199 * 10**9,
            True,
        ),
        (
            # three days since last report, penalty greater than frame rebase
            simple_blockstamp(3 * 225 * 32),
            [*simple_validators(0, 999), *simple_validators(1000, 1049, slashed=True)],
            simple_validators(1000, 1049, slashed=True),
            3 * 199 * 10**9,
            True,
        ),
        (
            # one day since last report, penalty equal report rebase
            simple_blockstamp(225 * 32),
            [*simple_validators(0, 999), *simple_validators(1000, 1049, slashed=True)],
            simple_validators(1000, 1049, slashed=True),
            200 * 10**9,
            False,
        ),
        (
            # one day since last report, penalty less report rebase
            simple_blockstamp(225 * 32),
            [*simple_validators(0, 999), *simple_validators(1000, 1049, slashed=True)],
            simple_validators(1000, 1049, slashed=True),
            201 * 10**9,
            False,
        ),
    ],
)
def test_is_high_midterm_slashing_penalty_pre_electra(
    blockstamp, all_validators, lido_validators, report_cl_rebase, expected_result
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
        2,
        lambda _: True,  # doesn't matter because consensus version == 2
        web3_converter=web3_converter,
        all_validators=all_validators,
        lido_validators=lido_validators,
        slashings=[],
        current_report_cl_rebase=report_cl_rebase,
        last_report_ref_slot=SlotNumber(0),
    )
    assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    ("blockstamp", "all_validators", "lido_validators", "slashings", "report_cl_rebase", "expected_result"),
    [
        (
            # no one slashed
            simple_blockstamp(0),
            simple_validators(0, 50),
            simple_validators(0, 9),
            [0] * EPOCHS_PER_SLASHINGS_VECTOR,
            0,
            False,
        ),
        (
            # no one Lido slashed
            simple_blockstamp(0),
            [*simple_validators(0, 49), *simple_validators(50, 99, slashed=True)],
            simple_validators(0, 9),
            [*([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 50)), *([32 * 10**9] * 50)],
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
            [0] * EPOCHS_PER_SLASHINGS_VECTOR,
            0,
            False,
        ),
        (
            # one day since last report, penalty greater than report rebase
            simple_blockstamp(225 * 32),  # 8160
            [*simple_validators(0, 999), *simple_validators(1000, 1049, slashed=True)],
            simple_validators(1000, 1049, slashed=True),
            [*([0] * 8110), *([32 * 10**9] * 50), *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 8160))],
            199 * 10**9,
            True,
        ),
        (
            # three days since last report, penalty greater than frame rebase
            simple_blockstamp(3 * 225 * 32),  # 24480, 24480 % 8192 = 8092
            [*simple_validators(0, 999), *simple_validators(1000, 1049, slashed=True)],
            simple_validators(1000, 1049, slashed=True),
            [*([0] * 8042), *([32 * 10**9] * 50), *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 8092))],
            3 * 199 * 10**9,
            True,  # Because penalty is 200 * 10**9 than one frame rebase
        ),
        (
            # one day since last report, penalty equal report rebase
            simple_blockstamp(225 * 32),
            [*simple_validators(0, 999), *simple_validators(1000, 1049, slashed=True)],
            simple_validators(1000, 1049, slashed=True),
            [*([0] * EPOCHS_PER_SLASHINGS_VECTOR)],
            228_571_427_200,
            False,
        ),
        (
            # one day since last report, penalty less report rebase
            simple_blockstamp(225 * 32),
            [*simple_validators(0, 999), *simple_validators(1000, 1049, slashed=True)],
            simple_validators(1000, 1049, slashed=True),
            [*([0] * EPOCHS_PER_SLASHINGS_VECTOR)],
            228_571_427_200 + 1,
            False,
        ),
    ],
)
def test_is_high_midterm_slashing_penalty_post_electra(
    blockstamp, all_validators, lido_validators, slashings, report_cl_rebase, expected_result
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
        lambda _: True,
        web3_converter=web3_converter,
        all_validators=all_validators,
        lido_validators=lido_validators,
        slashings=slashings,
        current_report_cl_rebase=report_cl_rebase,
        last_report_ref_slot=SlotNumber(0),
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
            {18: simple_validators(0, 9, slashed=True)},
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
                18: simple_validators(0, 9, slashed=True),
                19: simple_validators(10, 59, slashed=True, withdrawable_epoch="8417"),
            },
        ),
    ],
)
def test_get_per_frame_lido_validators_with_future_midterm_epoch(
    ref_epoch, future_midterm_penalty_lido_slashed_validators, expected_result
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
            {18: simple_validators(0, 0, slashed=True)},
            simple_validators(0, 0, slashed=True),
            100,
            {18: 0},
        ),
        (
            # all are slashed
            225,
            {18: simple_validators(0, 99, slashed=True)},
            simple_validators(0, 99, slashed=True),
            100,
            {18: 100 * 32 * 10**9},
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
                *simple_validators(10, 59, slashed=True, exit_epoch="8000", withdrawable_epoch="8417"),
            ],
            100,
            {18: 10 * 32 * 10**9, 19: 50 * 32 * 10**9},
        ),
        (
            # slashed in different epochs in different frames without determined shasling epochs
            225,
            {
                18: [
                    *simple_validators(0, 5),
                    *simple_validators(6, 9, slashed=True, exit_epoch="8192", withdrawable_epoch="8197"),
                ],
                19: [
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
        "is_electra_activated",
        "per_frame_validators",
        "slashings",
        "active_validators_count",
        "expected_result",
    ),
    [
        (225, 225, {}, [], 50000, {}),
        (
            # one is slashed before electra
            225,
            lambda epoch: epoch >= 4500,
            {18: simple_validators(0, 0, slashed=True)},
            [*([0] * EPOCHS_PER_SLASHINGS_VECTOR)],
            50000,
            {18: 0},
        ),
        (
            # one is slashed after electra
            225,
            lambda epoch: epoch >= 225,
            {18: simple_validators(0, 0, slashed=True)},
            [*([0] * 224), *([32 * 10**9]), *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 225))],
            50000,
            {18: 1_920_000},
        ),
        (
            # all are slashed before electra
            225,
            lambda epoch: epoch >= 4500,
            {18: simple_validators(0, 99, slashed=True)},
            [*([32 * 10**9] * 100), *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 100))],
            50000,
            {18: 0},
        ),
        (
            # all are slashed after electra
            350,
            lambda epoch: epoch >= 225,
            {18: simple_validators(0, 99, slashed=True)},
            [*([0] * 225), *([32 * 10**9] * 100), *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 325))],
            50000,
            {18: 19_200_000_000},
        ),
        (
            # slashed in different frames with determined slashing epochs in different forks
            225,
            lambda epoch: epoch >= 4200,
            {
                18: simple_validators(0, 0, slashed=True),
                19: simple_validators(10, 59, slashed=True, exit_epoch="8000", withdrawable_epoch="8417"),
            },
            [
                *([0] * 100),
                *([32 * 10**9]),
                *([0] * 10),
                *([32 * 10**9] * 50),
                *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 161)),
            ],
            50000,
            {18: 0, 19: 4_896_000_000},
        ),
        (
            # slashed in different epochs in different frames without determined slashing epochs in different forks
            225,
            lambda epoch: epoch >= 4200,
            {
                18: [
                    *simple_validators(0, 5),
                    *simple_validators(6, 9, slashed=True, exit_epoch="8192", withdrawable_epoch="8197"),
                ],
                19: [
                    *simple_validators(10, 29, slashed=True, exit_epoch="8000", withdrawable_epoch="8417"),
                    *simple_validators(30, 59, slashed=True, exit_epoch="8417", withdrawable_epoch="8419"),
                ],
            },
            [
                *([0] * 100),
                *([32 * 10**9] * 10),
                *([32 * 10**9] * 50),
                *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 160)),
            ],
            50000,
            {18: 0, 19: 5_760_000_000},
        ),
    ],
)
def test_get_future_midterm_penalty_sum_in_frames_post_electra(
    ref_epoch,
    is_electra_activated,
    per_frame_validators,
    slashings,
    active_validators_count,
    expected_result,
):
    result = MidtermSlashingPenalty.get_future_midterm_penalty_sum_in_frames_post_electra(
        EpochNumber(ref_epoch),
        is_electra_activated,
        slashings,
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
        "is_electra_activated",
        "total_balance",
        "slashings",
        "validators_in_frame",
        "expected_result",
    ),
    [
        # BEFORE ELECTRA
        (225, lambda _: False, 100 * 32 * 10**9, [], [], 0),
        (
            # one is slashed
            225,
            lambda _: False,
            100 * 32 * 10**9,
            [*([0] * 125), 32 * 10**9, *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 126))],
            simple_validators(0, 0, slashed=True),
            0,
        ),
        (
            # all are slashed
            225,
            lambda _: False,
            100 * 32 * 10**9,
            [*([32 * 10**9] * 100), *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 100))],
            simple_validators(0, 99, slashed=True),
            100 * 32 * 10**9,
        ),
        (
            # several are slashed
            225,
            lambda _: False,
            100 * 32 * 10**9,
            [*([64 * 10**9] * 2), *([0] * 10), *([32 * 10**9] * 6), *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 18))],
            simple_validators(0, 9, slashed=True),
            10 * 9 * 10**9,
        ),
        (
            # slashed in different epochs in different frames without determined slashing epochs
            225,
            lambda _: False,
            100 * 32 * 10**9,
            [*([32 * 10**9] * 6), *([0] * 219), *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 229)), *([32 * 10**9] * 4)],
            [
                *simple_validators(0, 5, slashed=True),
                *simple_validators(6, 9, slashed=True, exit_epoch="8192", withdrawable_epoch="8197"),
            ],
            10 * 9 * 10**9,
        ),
        # AFTER ELECTRA
        (
            225,
            lambda _: True,
            100 * 32 * 10**9,
            [],
            [],
            0,
        ),
        (
            # one is slashed
            225,
            lambda _: True,
            100 * 32 * 10**9,
            [*([0] * 125), 32 * 10**9, *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 126))],
            simple_validators(0, 0, slashed=True),
            960_000_000,
        ),
        (
            # all are slashed
            225,
            lambda _: True,
            100 * 32 * 10**9,
            [*([32 * 10**9] * 100), *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 100))],
            simple_validators(0, 99, slashed=True),
            100 * 32 * 10**9,
        ),
        (
            # several are slashed
            225,
            lambda _: True,
            100 * 32 * 10**9,
            [*([64 * 10**9] * 2), *([0] * 10), *([32 * 10**9] * 6), *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 18))],
            simple_validators(0, 9, slashed=True),
            96_000_000_000,
        ),
        (
            # slashed in different epochs in different frames without determined slashing epochs
            225,
            lambda _: True,
            100 * 32 * 10**9,
            [*([32 * 10**9] * 6), *([0] * 219), *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 229)), *([32 * 10**9] * 4)],
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
    is_electra_activated,
    total_balance,
    slashings,
    validators_in_frame,
    expected_result,
):
    result = MidtermSlashingPenalty.predict_midterm_penalty_in_frame_post_electra(
        report_ref_epoch=EpochNumber(ref_epoch),
        is_electra_activated=is_electra_activated,
        total_balance=total_balance,
        slashings=slashings,
        midterm_penalized_validators_in_frame=validators_in_frame,
    )
    assert result == expected_result


def test_midterm_penalty_prediction_in_pectra_transition_can_be_greater_than_before_pectra():
    epoch = EpochNumber(10)
    slashings = [*([32 * 10**9] * EPOCHS_PER_SLASHINGS_VECTOR)]
    total_balance = 100000 * 32 * 10**9

    validators_in_frame = [
        ValidatorFactory.build(
            balance=32 * 10**9,
            validator=ValidatorStateFactory.build(
                activation_epoch=10,
                withdrawable_epoch=(EPOCHS_PER_SLASHINGS_VECTOR // 2) + 50,
                slashed=True,
                effective_balance=32 * 10**9,
            ),
        ),
        ValidatorFactory.build(
            balance=32 * 10**9,
            validator=ValidatorStateFactory.build(
                activation_epoch=10,
                withdrawable_epoch=(EPOCHS_PER_SLASHINGS_VECTOR // 2) + 30,
                slashed=True,
                effective_balance=32 * 10**9,
            ),
        ),
    ]

    midterm_penalty_prediction_electra_not_activated = (
        MidtermSlashingPenalty.predict_midterm_penalty_in_frame_post_electra(
            report_ref_epoch=EpochNumber(epoch),
            is_electra_activated=lambda _: False,
            total_balance=total_balance,
            slashings=slashings,
            midterm_penalized_validators_in_frame=validators_in_frame,
        )
    )

    midterm_penalty_prediction_electra_activated_second = (
        MidtermSlashingPenalty.predict_midterm_penalty_in_frame_post_electra(
            report_ref_epoch=EpochNumber(epoch),
            is_electra_activated=lambda _: True,
            total_balance=total_balance,
            slashings=slashings,
            midterm_penalized_validators_in_frame=validators_in_frame[:1],
        )
    )

    midterm_penalty_prediction_electra_not_activated_first = (
        MidtermSlashingPenalty.predict_midterm_penalty_in_frame_post_electra(
            report_ref_epoch=EpochNumber(epoch),
            is_electra_activated=lambda _: False,
            total_balance=total_balance,
            slashings=slashings,
            midterm_penalized_validators_in_frame=validators_in_frame[1:],
        )
    )

    assert (
        midterm_penalty_prediction_electra_not_activated
        <= midterm_penalty_prediction_electra_activated_second + midterm_penalty_prediction_electra_not_activated_first
    )


# 50% active validators with 2048 EB and the rest part with 32 EB
half_electra = [
    *simple_validators(0, 250_000, effective_balance=MAX_EFFECTIVE_BALANCE),
    *simple_validators(250_001, 500_000, effective_balance=MAX_EFFECTIVE_BALANCE_ELECTRA),
]
# 20% active validators with 2048 EB and the rest part with 32 EB
part_electra = [
    *simple_validators(0, 10_000, effective_balance=MAX_EFFECTIVE_BALANCE_ELECTRA),
    *simple_validators(10_001, 500_000, effective_balance=MAX_EFFECTIVE_BALANCE),
]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("slashings", "active_validators", "expected_penalty", "midterm_penalty_epoch", "report_ref_epoch"),
    [
        (
            [
                *([MAX_EFFECTIVE_BALANCE] * 50),
                *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 100)),
                *([MAX_EFFECTIVE_BALANCE_ELECTRA] * 50),
            ],
            half_electra,
            19199968,
            4010,
            225,
        ),
        (
            [*([32 * 10**9] * 50), *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 100)), *([32 * 10**9] * 50)],
            part_electra,
            8_495_072,
            4010,
            225,
        ),
    ],
)
def test_get_validator_midterm_penalty_electra(
    slashings, active_validators, expected_penalty, midterm_penalty_epoch, report_ref_epoch
):
    result = MidtermSlashingPenalty.get_validator_midterm_penalty_electra(
        validator=simple_validators(0, 0)[0],
        slashings=slashings,
        total_balance=Gwei(sum(v.validator.effective_balance for v in active_validators)),
        midterm_penalty_epoch=midterm_penalty_epoch,
        report_ref_epoch=report_ref_epoch,
    )

    assert result == expected_penalty


def test_cut_slashings_basic():
    slashings = [Gwei(i) for i in range(EPOCHS_PER_SLASHINGS_VECTOR)]
    midterm_penalty_epoch = 20
    report_ref_epoch = 10

    result = MidtermSlashingPenalty._cut_slashings(slashings, midterm_penalty_epoch, report_ref_epoch)

    expected_indexes = {i % EPOCHS_PER_SLASHINGS_VECTOR for i in range(report_ref_epoch, midterm_penalty_epoch)}
    assert midterm_penalty_epoch not in expected_indexes
    expected = [slashings[i] for i in range(EPOCHS_PER_SLASHINGS_VECTOR) if i not in expected_indexes]

    assert result == expected, f"Expected {expected}, but got {result}"


def test_cut_slashings_incorrect_length():
    invalid_length = EPOCHS_PER_SLASHINGS_VECTOR - 1
    slashings = [Gwei(i) for i in range(invalid_length)]

    with pytest.raises(ValueError):
        MidtermSlashingPenalty._cut_slashings(slashings, 10, 20)


def test_cut_slashings_no_obsolete_indexes():
    slashings = [Gwei(i) for i in range(EPOCHS_PER_SLASHINGS_VECTOR)]
    midterm_penalty_epoch = 5
    report_ref_epoch = 5

    result = MidtermSlashingPenalty._cut_slashings(slashings, midterm_penalty_epoch, report_ref_epoch)

    assert result == slashings, f"Expected {slashings}, but got {result}"


def test_cut_slashings_all_removed():
    slashings = [Gwei(i) for i in range(EPOCHS_PER_SLASHINGS_VECTOR)]
    report_ref_epoch = 1
    midterm_penalty_epoch = report_ref_epoch + EPOCHS_PER_SLASHINGS_VECTOR  # Covers all indices

    result = MidtermSlashingPenalty._cut_slashings(slashings, midterm_penalty_epoch, report_ref_epoch)

    assert result == [], "Expected all elements to be removed, but some remain"


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
