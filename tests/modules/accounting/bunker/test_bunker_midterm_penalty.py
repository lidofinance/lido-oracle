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
def test_is_high_midterm_slashing_penalty(
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
        web3_converter,
        all_validators,
        lido_validators,
        slashings,
        report_cl_rebase,
        SlotNumber(0),
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
    (
        "ref_epoch",
        "per_frame_validators",
        "slashings",
        "active_validators_count",
        "expected_result",
    ),
    [
        (
            225,
            {18: simple_validators(0, 0, slashed=True)},
            [*([0] * 224), *([32 * 10**9]), *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 225))],
            50000,
            {18: 1_920_000},
        ),
        (
            350,
            {18: simple_validators(0, 99, slashed=True)},
            [*([0] * 225), *([32 * 10**9] * 100), *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 325))],
            50000,
            {18: 19_200_000_000},
        ),
    ],
)
def test_get_future_midterm_penalty_sum_in_frames(
    ref_epoch,
    per_frame_validators,
    slashings,
    active_validators_count,
    expected_result,
):
    result = MidtermSlashingPenalty.get_future_midterm_penalty_sum_in_frames(
        EpochNumber(ref_epoch),
        slashings,
        active_validators_count * 32 * 10**9,
        per_frame_validators,
    )

    assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    (
        "ref_epoch",
        "total_balance",
        "slashings",
        "validators_in_frame",
        "expected_result",
    ),
    [
        (
            225,
            100 * 32 * 10**9,
            [],
            [],
            0,
        ),
        (
            # one is slashed
            225,
            100 * 32 * 10**9,
            [*([0] * 125), 32 * 10**9, *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 126))],
            simple_validators(0, 0, slashed=True),
            960_000_000,
        ),
        (
            # all are slashed
            225,
            100 * 32 * 10**9,
            [*([32 * 10**9] * 100), *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 100))],
            simple_validators(0, 99, slashed=True),
            100 * 32 * 10**9,
        ),
        (
            # several are slashed
            225,
            100 * 32 * 10**9,
            [*([64 * 10**9] * 2), *([0] * 10), *([32 * 10**9] * 6), *([0] * (EPOCHS_PER_SLASHINGS_VECTOR - 18))],
            simple_validators(0, 9, slashed=True),
            96_000_000_000,
        ),
        (
            # slashed in different epochs in different frames without determined slashing epochs
            225,
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
def test_predict_midterm_penalty_in_frame(
    ref_epoch,
    total_balance,
    slashings,
    validators_in_frame,
    expected_result,
):
    result = MidtermSlashingPenalty.predict_midterm_penalty_in_frame(
        report_ref_epoch=EpochNumber(ref_epoch),
        total_balance=total_balance,
        slashings=slashings,
        midterm_penalized_validators_in_frame=validators_in_frame,
    )
    assert result == expected_result


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
def test_get_validator_midterm_penalty(
    slashings, active_validators, expected_penalty, midterm_penalty_epoch, report_ref_epoch
):
    result = MidtermSlashingPenalty.get_validator_midterm_penalty(
        validator=simple_validators(0, 0)[0],
        slashings=slashings,
        total_balance=Gwei(sum(v.validator.effective_balance for v in active_validators)),
        midterm_penalty_epoch=midterm_penalty_epoch,
        report_ref_epoch=report_ref_epoch,
    )

    assert result == expected_penalty


@pytest.mark.unit
def test_cut_slashings_basic():
    slashings = [Gwei(i) for i in range(EPOCHS_PER_SLASHINGS_VECTOR)]
    midterm_penalty_epoch = 20
    report_ref_epoch = 10

    result = MidtermSlashingPenalty._cut_slashings(slashings, midterm_penalty_epoch, report_ref_epoch)

    expected_indexes = {i % EPOCHS_PER_SLASHINGS_VECTOR for i in range(report_ref_epoch, midterm_penalty_epoch)}
    assert midterm_penalty_epoch not in expected_indexes
    expected = [slashings[i] for i in range(EPOCHS_PER_SLASHINGS_VECTOR) if i not in expected_indexes]

    assert result == expected, f"Expected {expected}, but got {result}"


@pytest.mark.unit
def test_cut_slashings_incorrect_length():
    invalid_length = EPOCHS_PER_SLASHINGS_VECTOR - 1
    slashings = [Gwei(i) for i in range(invalid_length)]

    with pytest.raises(ValueError):
        MidtermSlashingPenalty._cut_slashings(slashings, 10, 20)


@pytest.mark.unit
def test_cut_slashings_no_obsolete_indexes():
    slashings = [Gwei(i) for i in range(EPOCHS_PER_SLASHINGS_VECTOR)]
    midterm_penalty_epoch = 5
    report_ref_epoch = 5

    result = MidtermSlashingPenalty._cut_slashings(slashings, midterm_penalty_epoch, report_ref_epoch)

    assert result == slashings, f"Expected {slashings}, but got {result}"


@pytest.mark.unit
def test_cut_slashings_all_removed():
    slashings = [Gwei(i) for i in range(EPOCHS_PER_SLASHINGS_VECTOR)]
    report_ref_epoch = 1
    midterm_penalty_epoch = report_ref_epoch + EPOCHS_PER_SLASHINGS_VECTOR  # Covers all indices

    result = MidtermSlashingPenalty._cut_slashings(slashings, midterm_penalty_epoch, report_ref_epoch)

    assert result == [], "Expected all elements to be removed, but some remain"


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
