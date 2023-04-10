import pytest

from src.constants import FAR_FUTURE_EPOCH
from src.providers.consensus.typings import Validator, ValidatorStatus, ValidatorState
from src.services.bunker_cases.abnormal_cl_rebase import AbnormalClRebase
from src.services.bunker_cases.typings import BunkerConfig
from tests.modules.accounting.bunker.conftest import simple_ref_blockstamp, simple_key, simple_blockstamp


def simple_validators(
    from_index: int,
    to_index: int,
    balance=str(32 * 10**9),
    effective_balance=str(32 * 10**9),
) -> list[Validator]:
    validators = []
    for index in range(from_index, to_index + 1):
        validator = Validator(
            index=str(index),
            balance=balance,
            status=ValidatorStatus.ACTIVE_ONGOING,
            validator=ValidatorState(
                pubkey=f"0x{index}",
                withdrawal_credentials='',
                effective_balance=effective_balance,
                slashed=False,
                activation_eligibility_epoch='',
                activation_epoch='0',
                exit_epoch=FAR_FUTURE_EPOCH,
                withdrawable_epoch=FAR_FUTURE_EPOCH,
            ),
        )
        validators.append(validator)
    return validators


@pytest.mark.unit
@pytest.mark.parametrize(
    ("blockstamp", "frame_cl_rebase", "nearest_epoch_distance", "far_epoch_distance", "expected_is_abnormal"),
    [
        (simple_ref_blockstamp(40), 378585832, 0, 0, False),  # < mistake rate
        (simple_ref_blockstamp(40), 378585831.6, 0, 0, False),  # == mistake rate and no check specific rebase
        (simple_ref_blockstamp(40), 378585830, 10, 20, False),  # > mistake rate but specific rebase is positive
        (simple_ref_blockstamp(40), 378585830, 10, 10, False),  # > mistake rate but specific rebase is positive
        (simple_ref_blockstamp(40), 378585830, 0, 0, True),  # > mistake rate and no check specific rebase
        (simple_ref_blockstamp(20), 126195276, 10, 20, True),  # > mistake rate and specific rebase is negative
        (simple_ref_blockstamp(20), 126195276, 10, 10, True),  # > mistake rate and specific rebase is negative
    ],
)
def test_is_abnormal_cl_rebase(
    blockstamp,
    abnormal_case,
    mock_get_accounting_last_processing_ref_slot,
    mock_get_used_lido_keys,
    mock_get_eth_distributed_events,
    mock_get_withdrawal_vault_balance,
    mock_get_blockstamp,
    frame_cl_rebase,
    nearest_epoch_distance,
    far_epoch_distance,
    expected_is_abnormal,
):
    all_validators = abnormal_case.w3.cc.get_validators(blockstamp)
    lido_validators = abnormal_case.w3.cc.get_validators(blockstamp)[3:6]
    abnormal_case.b_conf = BunkerConfig(
        normalized_cl_reward_per_epoch=64,
        normalized_cl_reward_mistake_rate=0.1,
        rebase_check_nearest_epoch_distance=nearest_epoch_distance,
        rebase_check_distant_epoch_distance=far_epoch_distance,
    )
    result = abnormal_case.is_abnormal_cl_rebase(blockstamp, all_validators, lido_validators, frame_cl_rebase)

    assert result == expected_is_abnormal


@pytest.mark.unit
@pytest.mark.parametrize(
    ("blockstamp", "expected_rebase"),
    [
        (simple_ref_blockstamp(40), 420650924),
        (simple_ref_blockstamp(20), 140216974),
        (simple_ref_blockstamp(123), 1120376622),
    ],
)
def test_calculate_lido_normal_cl_rebase(
    abnormal_case,
    mock_get_used_lido_keys,
    mock_get_accounting_last_processing_ref_slot,
    mock_get_eth_distributed_events,
    mock_get_withdrawal_vault_balance,
    mock_get_blockstamp,
    blockstamp,
    expected_rebase,
):
    abnormal_case.all_validators = abnormal_case.w3.cc.get_validators(blockstamp)
    abnormal_case.lido_validators = abnormal_case.w3.cc.get_validators(blockstamp)[3:6]
    abnormal_case.lido_keys = abnormal_case.w3.kac.get_used_lido_keys(blockstamp)

    result = abnormal_case._calculate_lido_normal_cl_rebase(blockstamp)

    assert result == expected_rebase


@pytest.mark.unit
@pytest.mark.parametrize(
    ("blockstamp", "nearest_epoch_distance", "far_epoch_distance", "expected_is_negative"),
    [
        (simple_ref_blockstamp(40), 10, 20, False),
        (simple_ref_blockstamp(20), 10, 20, True),
        (simple_ref_blockstamp(20), 10, 10, True),
        (simple_ref_blockstamp(33), 2, 33, True),
        (
            simple_ref_blockstamp(20),
            20,
            10,
            "nearest_slot=0 should be between distant_slot=10 and ref_slot=20 in specific CL rebase calculation",
        ),
        (
            simple_ref_blockstamp(20),
            10,
            -10,
            "nearest_slot=10 should be between distant_slot=30 and ref_slot=20 in specific CL rebase calculation",
        ),
    ],
)
def test_is_negative_specific_cl_rebase(
    abnormal_case,
    mock_get_eth_distributed_events,
    mock_get_withdrawal_vault_balance,
    mock_get_blockstamp,
    blockstamp,
    nearest_epoch_distance,
    far_epoch_distance,
    expected_is_negative,
):
    abnormal_case.lido_validators = abnormal_case.w3.cc.get_validators(blockstamp)[3:6]
    abnormal_case.lido_keys = [
        simple_key('0x03'),
        simple_key('0x04'),
        simple_key('0x05'),
    ]
    abnormal_case.b_conf = BunkerConfig(
        normalized_cl_reward_per_epoch=64,
        normalized_cl_reward_mistake_rate=0.1,
        rebase_check_nearest_epoch_distance=nearest_epoch_distance,
        rebase_check_distant_epoch_distance=far_epoch_distance,
    )
    if isinstance(expected_is_negative, str):
        with pytest.raises(ValueError, match=expected_is_negative):
            abnormal_case._is_negative_specific_cl_rebase(blockstamp)
    else:
        result = abnormal_case._is_negative_specific_cl_rebase(blockstamp)
        assert result == expected_is_negative


@pytest.mark.unit
@pytest.mark.parametrize(
    ("blockstamp", "expected_blockstamps"),
    [
        (simple_ref_blockstamp(40), (simple_blockstamp(30), simple_blockstamp(20))),
        (simple_ref_blockstamp(20), (simple_blockstamp(10), simple_blockstamp(0))),
        (simple_ref_blockstamp(444444), (simple_blockstamp(444431), simple_blockstamp(444420))),
    ],
)
def test_get_nearest_and_distant_blockstamps(
    abnormal_case,
    mock_get_blockstamp,
    blockstamp,
    expected_blockstamps,
):
    abnormal_case.b_conf = BunkerConfig(
        normalized_cl_reward_per_epoch=64,
        normalized_cl_reward_mistake_rate=0.1,
        rebase_check_nearest_epoch_distance=10,
        rebase_check_distant_epoch_distance=20,
    )

    nearest_blockstamp, distant_blockstamp = abnormal_case._get_nearest_and_distant_blockstamps(blockstamp)

    assert nearest_blockstamp == expected_blockstamps[0]
    assert distant_blockstamp == expected_blockstamps[1]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("prev_blockstamp", "blockstamp", "expected_rebase"),
    [
        (simple_ref_blockstamp(0), simple_ref_blockstamp(10), 100),
        (simple_ref_blockstamp(10), simple_ref_blockstamp(20), -32000100800),
        (
            simple_ref_blockstamp(20),
            simple_ref_blockstamp(30),
            "Validators count diff should be positive or 0. Something went wrong with CL API",
        ),
    ],
)
def test_calculate_cl_rebase_between_blocks(
    abnormal_case,
    mock_get_eth_distributed_events,
    mock_get_withdrawal_vault_balance,
    mock_get_blockstamp,
    prev_blockstamp,
    blockstamp,
    expected_rebase,
):
    abnormal_case.lido_validators = abnormal_case.w3.cc.get_validators(blockstamp)[3:6]
    abnormal_case.lido_keys = [
        simple_key('0x03'),
        simple_key('0x04'),
        simple_key('0x05'),
    ]
    if isinstance(expected_rebase, str):
        with pytest.raises(ValueError, match=expected_rebase):
            abnormal_case._calculate_cl_rebase_between_blocks(prev_blockstamp, blockstamp)
    else:
        result = abnormal_case._calculate_cl_rebase_between_blocks(prev_blockstamp, blockstamp)
        assert result == expected_rebase


@pytest.mark.unit
@pytest.mark.parametrize(
    ("blockstamp", "expected_result"),
    [
        (simple_ref_blockstamp(40), 98001157445),
        (simple_ref_blockstamp(20), 77999899300),
    ],
)
def test_get_lido_validators_balance_with_vault(
    abnormal_case,
    mock_get_withdrawal_vault_balance,
    blockstamp,
    expected_result,
):
    lido_validators = abnormal_case.w3.cc.get_validators(blockstamp)[3:6]

    result = abnormal_case._get_lido_validators_balance_with_vault(blockstamp, lido_validators)

    assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    ("prev_blockstamp", "blockstamp", "expected_result"),
    [
        (simple_ref_blockstamp(0), simple_ref_blockstamp(10), 1 * 10**9),
        (simple_ref_blockstamp(10), simple_ref_blockstamp(20), 0),
        (simple_ref_blockstamp(20), simple_ref_blockstamp(30), "More than one ETHDistributed event found"),
    ],
)
def test_get_withdrawn_from_vault_between(
    abnormal_case, mock_get_eth_distributed_events, prev_blockstamp, blockstamp, expected_result
):
    if isinstance(expected_result, str):
        with pytest.raises(ValueError, match=expected_result):
            abnormal_case._get_withdrawn_from_vault_between_blocks(prev_blockstamp, blockstamp)
    else:
        result = abnormal_case._get_withdrawn_from_vault_between_blocks(prev_blockstamp, blockstamp)
        assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    ("curr_validators", "prev_validators", "expected_result"),
    [
        ([], [], 0),
        (simple_validators(0, 9), simple_validators(0, 9), 0),
        (simple_validators(0, 11), simple_validators(0, 9), 2 * 32 * 10**9),
        (
            simple_validators(0, 9),
            simple_validators(0, 10),
            "Validators count diff should be positive or 0. Something went wrong with CL API",
        ),
    ],
)
def test_get_validators_diff_in_gwei(prev_validators, curr_validators, expected_result):
    if isinstance(expected_result, str):
        with pytest.raises(ValueError, match=expected_result):
            AbnormalClRebase.calculate_validators_count_diff_in_gwei(prev_validators, curr_validators)
    else:
        result = AbnormalClRebase.calculate_validators_count_diff_in_gwei(prev_validators, curr_validators)
        assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    ("curr_validators", "last_report_validators", "expected_result"),
    [
        ([], [], 0),
        (simple_validators(0, 9), simple_validators(0, 9), 10 * 32 * 10**9),
        (simple_validators(0, 9), simple_validators(0, 9, effective_balance=31 * 10**9), 10 * int(31.5 * 10**9)),
    ],
)
def test_get_mean_effective_balance_sum(curr_validators, last_report_validators, expected_result):
    result = AbnormalClRebase.get_mean_sum_of_effective_balance(
        simple_ref_blockstamp(0), simple_ref_blockstamp(0), curr_validators, last_report_validators
    )

    assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(
    ("distant_slot", "nearest_slot", "ref_slot", "expected_result"),
    [
        (1, 2, 3, None),
        (2, 1, 3, "nearest_slot=1 should be between distant_slot=2 and ref_slot=3 in specific CL rebase calculation"),
        (3, 2, 1, "nearest_slot=2 should be between distant_slot=3 and ref_slot=1 in specific CL rebase calculation"),
        (3, 1, 2, "nearest_slot=1 should be between distant_slot=3 and ref_slot=2 in specific CL rebase calculation"),
    ],
)
def test_validate_slot_distance(distant_slot, nearest_slot, ref_slot, expected_result):
    if expected_result is None:
        assert AbnormalClRebase.validate_slot_distance(distant_slot, nearest_slot, ref_slot) is None
    else:
        with pytest.raises(ValueError, match=expected_result):
            AbnormalClRebase.validate_slot_distance(distant_slot, nearest_slot, ref_slot)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("validators", "expected_balance"),
    [
        ([], 0),
        (simple_validators(0, 9), 10 * 32 * 10**9),
        (
            simple_validators(0, 9, balance=str(int(31.75 * 10**9)), effective_balance=str(32 * 10**9)),
            10 * int(31.75 * 10**9),
        ),
        (simple_validators(0, 9, balance=str(10**9)), 10 * 10**9),
    ],
)
def test_calculate_real_balance(validators, expected_balance):
    total_effective_balance = AbnormalClRebase.calculate_validators_balance_sum(validators)

    assert total_effective_balance == expected_balance


@pytest.mark.unit
@pytest.mark.parametrize(
    ("epoch_passed", "mean_lido", "mean_total", "expected"),
    [
        (0, 32 * 152261 * 10**9, 32 * 517310 * 10**9, 0),
        (1, 32 * 152261 * 10**9, 32 * 517310 * 10**9, 2423640516),
        (225, 32 * 152261 * 10**9, 32 * 517310 * 10**9, 545319116173),
        (450, 32 * 152261 * 10**9, 32 * 517310 * 10**9, 1090638232347),
    ],
)
def test_calculate_normal_cl_rebase(epoch_passed, mean_lido, mean_total, expected):
    bunker_config = BunkerConfig(
        normalized_cl_reward_per_epoch=64,
        normalized_cl_reward_mistake_rate=0.1,
        rebase_check_nearest_epoch_distance=0,
        rebase_check_distant_epoch_distance=0,
    )

    normal_cl_rebase = AbnormalClRebase.calculate_normal_cl_rebase(
        bunker_config,
        mean_total,
        mean_lido,
        epoch_passed,
    )
    assert normal_cl_rebase == expected
