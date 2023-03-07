import pytest

from src.providers.consensus.typings import Validator, ValidatorStatus, ValidatorState
from src.services.bunker import BunkerConfig
from src.services.bunker_cases.abnormal_cl_rebase import AbnormalClRebase
from src.typings import BlockStamp, ReferenceBlockStamp
from tests.modules.accounting.bunker.test_bunker_medterm_penalty import simple_blockstamp


@pytest.mark.unit
@pytest.mark.parametrize(
    ("blockstamp", "frame_cl_rebase", "nearest_epoch_distance", "far_epoch_distance", "expected_is_abnormal"),
    [
        (simple_blockstamp(40, '0x40'), 504781109, 0, 0, False),    # > normal cl rebase
        (simple_blockstamp(40, '0x40'), 504781108, 0, 0, False),    # == normal cl rebase and no check specific rebase
        (simple_blockstamp(40, '0x40'), 504781107, 10, 20, False),  # < normal cl rebase but specific rebase is positive
        (simple_blockstamp(40, '0x40'), 504781107, 10, 10, False),  # < normal cl rebase but specific rebase is positive
        (simple_blockstamp(40, '0x40'), 504781107, 0, 0, True),     # < normal cl rebase and no check specific rebase
        (simple_blockstamp(20, '0x20'), 252390553, 10, 20, True),   # < normal cl rebase and specific rebase is negative
        (simple_blockstamp(20, '0x20'), 252390553, 10, 10, True),   # < normal cl rebase and specific rebase is negative
    ],
)
def test_is_abnormal_cl_rebase(
    blockstamp,
    abnormal_case,
    mock_get_eth_distributed_events,
    mock_get_withdrawal_vault_balance,
    mock_get_first_non_missed_slot,
    frame_cl_rebase,
    nearest_epoch_distance,
    far_epoch_distance,
    expected_is_abnormal
):
    abnormal_case.b_conf = BunkerConfig(
        normalized_cl_reward_per_epoch=64,
        normalized_cl_reward_mistake_rate=0.1,
        rebase_check_nearest_epoch_distance=nearest_epoch_distance,
        rebase_check_distant_epoch_distance=far_epoch_distance
    )
    result = abnormal_case.is_abnormal_cl_rebase(blockstamp, frame_cl_rebase)

    assert result == expected_is_abnormal


@pytest.mark.unit
@pytest.mark.parametrize(
    ("blockstamp", "expected_rebase"),
    [
        (simple_blockstamp(40, '0x40'), 378585831),
        (simple_blockstamp(20, '0x20'), 126195277),
    ]
)
def test_get_normal_cl_rebase(
    abnormal_case,
    mock_get_eth_distributed_events,
    mock_get_withdrawal_vault_balance,
    mock_get_first_non_missed_slot,
    blockstamp,
    expected_rebase
):
    abnormal_case.last_report_ref_slot = 10

    result = abnormal_case._get_normal_cl_rebase(blockstamp)

    assert result == expected_rebase


@pytest.mark.unit
@pytest.mark.parametrize(
    ("blockstamp", "nearest_epoch_distance", "far_epoch_distance", "expected_is_negative"),
    [
        (simple_blockstamp(40, '0x40'), 10, 20, False),
        (simple_blockstamp(20, '0x20'), 10, 20, True),
        (simple_blockstamp(20, '0x20'), 10, 10, True),
        (
            simple_blockstamp(20, '0x20'),
            20,
            10,
            ValueError("nearest_slot=0 should be less than distant_slot=10 in specific CL rebase calculation")),
        (
            simple_blockstamp(20, '0x20'),
            10,
            500,
            ValueError("distant_slot=-480 should be greater than self.last_report_ref_slot=0 in specific CL rebase calculation")
        ),
    ]
)
def test_is_negative_specific_cl_rebase(
    abnormal_case,
    mock_get_eth_distributed_events,
    mock_get_withdrawal_vault_balance,
    mock_get_first_non_missed_slot,
    blockstamp,
    nearest_epoch_distance,
    far_epoch_distance,
    expected_is_negative,
):
    abnormal_case.b_conf = BunkerConfig(
        normalized_cl_reward_per_epoch=64,
        normalized_cl_reward_mistake_rate=0.1,
        rebase_check_nearest_epoch_distance=nearest_epoch_distance,
        rebase_check_distant_epoch_distance=far_epoch_distance
    )
    if isinstance(expected_is_negative, Exception):
        with pytest.raises(expected_is_negative.__class__, match=expected_is_negative.args[0]):
            abnormal_case._is_negative_specific_cl_rebase(blockstamp)
    else:
        result = abnormal_case._is_negative_specific_cl_rebase(blockstamp)
        assert result == expected_is_negative


@pytest.mark.unit
@pytest.mark.parametrize(
    ("prev_blockstamp", "blockstamp", "expected_rebase"),
    [
        (simple_blockstamp(0, '0x0'), simple_blockstamp(10, '0x10'), 100),
        (simple_blockstamp(10, '0x10'), simple_blockstamp(20, '0x20'), -32000100800),
        (
            simple_blockstamp(20, '0x20'),
            simple_blockstamp(30, '0x30'),
            ValueError("Validators count diff should be positive or 0. Something went wrong with CL API")
        ),
    ]
)
def test_calculate_cl_rebase_between(
    abnormal_case,
    mock_get_eth_distributed_events,
    mock_get_withdrawal_vault_balance,
    mock_get_first_non_missed_slot,
    prev_blockstamp,
    blockstamp,
    expected_rebase,
):
    if isinstance(expected_rebase, Exception):
        with pytest.raises(expected_rebase.__class__, match=expected_rebase.args[0]):
            abnormal_case._calculate_cl_rebase_between(prev_blockstamp, blockstamp)
    else:
        result = abnormal_case._calculate_cl_rebase_between(prev_blockstamp, blockstamp)
        assert result == expected_rebase


@pytest.mark.unit
@pytest.mark.parametrize(
    ("from_block", "to_block", "expected_result"),
    [(0, 10, 1 * 10 ** 9), (10, 20, 0), (20, 30, ValueError("More than one ETHDistributed event found"))]
)
def test_get_withdrawn_from_vault_between(
    abnormal_case, mock_get_eth_distributed_events, from_block, to_block, expected_result
):
    def b(block_number: int) -> BlockStamp:
        return ReferenceBlockStamp('', '', block_number, '', block_number, 0, block_number, 0)

    if isinstance(expected_result, Exception):
        with pytest.raises(expected_result.__class__, match=expected_result.args[0]):
            abnormal_case._get_withdrawn_from_vault_between(b(from_block), b(to_block))
    else:
        result = abnormal_case._get_withdrawn_from_vault_between(b(from_block), b(to_block))
        assert result == expected_result


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


@pytest.mark.unit
@pytest.mark.parametrize(("validators", "expected_balance"), test_data_calculate_real_balance)
def test_calculate_real_balance(validators, expected_balance):
    total_effective_balance = AbnormalClRebase.calculate_real_balance(validators)
    assert total_effective_balance == expected_balance


@pytest.mark.unit
@pytest.mark.parametrize(
    ("epoch_passed", "mean_lido", "mean_total", "expected"),
    [(225, 32 * 152261 * 10 ** 9, 32 * 517310 * 10 ** 9, 490787204556),
     (450, 32 * 152261 * 10 ** 9, 32 * 517310 * 10 ** 9, 981574409112)]
)
def test_calculate_normal_cl_rebase(abnormal_case, epoch_passed, mean_lido, mean_total, expected):
    normal_cl_rebase = abnormal_case._calculate_normal_cl_rebase(epoch_passed, mean_lido, mean_total)
    assert normal_cl_rebase == expected
