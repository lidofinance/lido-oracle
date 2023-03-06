from unittest.mock import Mock

import pytest

from src.modules.accounting.typings import LidoReportRebase
from src.modules.submodules.consensus import FrameConfig
from src.modules.submodules.typings import ChainConfig
from src.providers.consensus.typings import Validator, ValidatorStatus, ValidatorState
from src.services.bunker import BunkerService, BunkerConfig
from src.providers.keys.typings import LidoKey
from src.typings import EpochNumber, BlockNumber, BlockStamp, ReferenceBlockStamp
from src.web3py.extensions import LidoContracts


def simple_blockstamp(block_number: int, state_root: str) -> BlockStamp:
    return ReferenceBlockStamp('', state_root, block_number, '', block_number, 0, block_number, block_number)


def simple_key(pubkey: str) -> LidoKey:
    key = object.__new__(LidoKey)
    key.key = pubkey
    return key


def simple_validator(index, pubkey, balance, slashed=False, withdrawable_epoch='') -> Validator:
    return Validator(
        index=str(index),
        balance=str(balance),
        status=ValidatorStatus.ACTIVE_ONGOING,
        validator=ValidatorState(
            pubkey=pubkey,
            withdrawal_credentials='',
            effective_balance=str(32 * 10 ** 9),
            slashed=slashed,
            activation_eligibility_epoch='',
            activation_epoch='0',
            exit_epoch='100500',
            withdrawable_epoch=withdrawable_epoch,
        )
    )


@pytest.fixture
def mock_get_first_non_missed_slot(monkeypatch):

    def _get_first_non_missed_slot(_, ref_slot, last_finalized_slot_number, ref_epoch):

        slots = {
            0: simple_blockstamp(0, '0x0'),
            10: simple_blockstamp(10, '0x10'),
            20: simple_blockstamp(20, '0x20'),
            30: simple_blockstamp(30, '0x30'),
        }

        return slots[ref_slot]

    monkeypatch.setattr(
        'src.services.bunker_cases.abnormal_cl_rebase.get_first_non_missed_slot', Mock(side_effect=_get_first_non_missed_slot)
    )


@pytest.fixture
def mock_get_eth_distributed_events(bunker):

    def _get_eth_distributed_events(from_block: BlockNumber, to_block: BlockNumber):
        events = {
            (1, 10): [{'args': {'withdrawalsWithdrawn': 1 * 10 ** 18}}],
            (1, 20): [{'args': {'withdrawalsWithdrawn': 1 * 10 ** 18}}],
            (11, 20): [],
            (21, 30): [{'args': {'withdrawalsWithdrawn': 7 * 10 ** 18}}, {'args': {'withdrawalsWithdrawn': 5 * 10 ** 18}}],
            (21, 40): [{'args': {'withdrawalsWithdrawn': 12 * 10 ** 18}}],
            (31, 40): [],
        }
        return events[(from_block, to_block)]

    bunker._get_eth_distributed_events = Mock(side_effect=_get_eth_distributed_events)


@pytest.fixture
def mock_get_total_supply(bunker):

    def _get_total_supply(block: BlockStamp):

        supplies = {
            0: 15 * 10 ** 18,
        }

        return supplies[block.block_number]

    bunker._get_total_supply = Mock(side_effect=_get_total_supply)


@pytest.fixture
def mock_get_withdrawal_vault_balance(bunker):
    def _get_withdrawal_vault_balance(blockstamp: BlockStamp):
        balance = {
            0: 15 * 10 ** 18,
            10: 14 * 10 ** 18,
            20: 14 * 10 ** 18,
            30: 2 * 10 ** 18,
            40: 2 * 10 ** 18,
        }
        return balance[blockstamp.block_number]

    bunker.w3.lido_contracts.get_withdrawal_balance = Mock(side_effect=_get_withdrawal_vault_balance)


@pytest.fixture
def mock_get_validators(bunker):

    def _get_validators(state: ReferenceBlockStamp, _=None):
        validators = {
            0: [
                simple_validator(0, '0x00', 32 * 10 ** 9),
                simple_validator(1, '0x01', 32 * 10 ** 9),
                simple_validator(2, '0x02', 32 * 10 ** 9),
                simple_validator(3, '0x03', 32 * 10 ** 9),
                simple_validator(4, '0x04', 32 * 10 ** 9),
                simple_validator(5, '0x05', 32 * 10 ** 9),
            ],
            10: [
                simple_validator(0, '0x00', 15 + 32 * 10 ** 9),
                simple_validator(1, '0x01', 17 + 32 * 10 ** 9),
                simple_validator(2, '0x02', 63 + 32 * 10 ** 9),
                simple_validator(3, '0x03', (32 * 10 ** 9) + 1),
                simple_validator(4, '0x04', 32 * 10 ** 9),
                simple_validator(5, '0x05', (32 * 10 ** 9) + 99),
            ],
            20: [
                simple_validator(0, '0x00', 32 * 10 ** 9),
                simple_validator(1, '0x01', 32 * 10 ** 9),
                simple_validator(2, '0x02', 32 * 10 ** 9),
                simple_validator(3, '0x03', (32 * 10 ** 9) - 200),
                simple_validator(4, '0x04', 0),
                simple_validator(5, '0x05', (32 * 10 ** 9) - 100500),
            ],
            30: [
                simple_validator(0, '0x00', 32 * 10 ** 9),
                simple_validator(1, '0x01', 32 * 10 ** 9),
                simple_validator(2, '0x02', 32 * 10 ** 9),
                simple_validator(3, '0x03', 32 * 10 ** 9),
                simple_validator(4, '0x04', 32 * 10 ** 9),
            ],
            40: [
                simple_validator(0, '0x00', 32 * 10 ** 9),
                simple_validator(1, '0x01', 32 * 10 ** 9),
                simple_validator(2, '0x02', 32 * 10 ** 9),
                simple_validator(3, '0x03', (32 * 10 ** 9) + 333333),
                simple_validator(4, '0x04', 32 * 10 ** 9),
                simple_validator(5, '0x05', (32 * 10 ** 9) + 824112),
            ],
            1000: [
                simple_validator(0, '0x00', 32 * 10 ** 9),
                simple_validator(1, '0x01', 32 * 10 ** 9),
                simple_validator(2, '0x02', 32 * 10 ** 9),
                simple_validator(3, '0x03', 32 * 10 ** 9, slashed=True, withdrawable_epoch='10001'),
                simple_validator(4, '0x04', 32 * 10 ** 9, slashed=True, withdrawable_epoch='10001'),
                simple_validator(5, '0x05', 32 * 10 ** 9, slashed=True, withdrawable_epoch='10001'),
                *[simple_validator(i, f'0x0{i}', 32 * 10 ** 9) for i in range(6, 200)],
            ]
        }
        return validators[state.slot_number]

    bunker.w3.cc.get_validators_no_cache = Mock(side_effect=_get_validators)


@pytest.fixture
def bunker(web3, lido_validators) -> BunkerService:
    """Minimal initialized bunker service"""
    service = BunkerService(web3)
    service.last_report_ref_slot = 0
    service.b_conf = BunkerConfig(
        normalized_cl_reward_per_epoch=64,
        normalized_cl_reward_mistake_rate=0.1,
        rebase_check_nearest_epoch_distance=4,
        rebase_check_distant_epoch_distance=25
    )
    service.f_conf = FrameConfig(
        initial_epoch=EpochNumber(0),
        epochs_per_frame=EpochNumber(225),
        fast_lane_length_slots=0,
    )
    service.lido_keys = {
        '0x03': simple_key('0x03'),
        '0x04': simple_key('0x04'),
        '0x05': simple_key('0x05'),
    }
    service.w3.lido_contracts = object.__new__(LidoContracts)
    service.w3.lido_contracts.w3 = web3
    return service


@pytest.mark.unit
@pytest.mark.parametrize(
    ("simulated_post_total_pooled_ether", "expected_rebase"),
    [
        (15 * 10 ** 18, 0),
        (12 * 10 ** 18, -3 * 10 ** 9),
        (18 * 10 ** 18, 3 * 10 ** 9),
    ]
)
def test_get_cl_rebase_for_frame(
    bunker,
    mock_get_total_supply,
    simulated_post_total_pooled_ether,
    expected_rebase,
):
    blockstamp = simple_blockstamp(0, '0x0')
    bunker.simulated_cl_rebase = LidoReportRebase(
        post_total_pooled_ether=simulated_post_total_pooled_ether,
        post_total_shares=0,
        withdrawals=0,
        el_reward=0,
    )

    result = bunker._get_cl_rebase_for_current_report(blockstamp)

    assert result == expected_rebase


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
    bunker.lido_validators = {
        v.validator.pubkey: v for v in bunker.w3.cc.get_validators(blockstamp)[_from:_to]
    }
    bunker.all_validators = {
        v.validator.pubkey: v for v in bunker.w3.cc.get_validators(blockstamp)
    }

    result = bunker.is_high_midterm_slashing_penalty(blockstamp, frame_cl_rebase)
    assert result == expected_is_high_midterm_slashing_penalty


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
    ]
)
def test_is_abnormal_cl_rebase(
    bunker,
    mock_get_eth_distributed_events,
    mock_get_withdrawal_vault_balance,
    mock_get_validators,
    mock_get_first_non_missed_slot,
    blockstamp,
    frame_cl_rebase,
    nearest_epoch_distance,
    far_epoch_distance,
    expected_is_abnormal
):
    bunker.last_report_ref_slot = 0
    bunker.c_conf = ChainConfig(
        slots_per_epoch=1,
        seconds_per_slot=12,
        genesis_time=0,
    )
    bunker.b_conf.rebase_check_nearest_epoch_distance = nearest_epoch_distance
    bunker.b_conf.rebase_check_distant_epoch_distance = far_epoch_distance
    bunker.all_validators = {
        v.validator.pubkey: v for v in bunker.w3.cc.get_validators(blockstamp)
    }
    bunker.lido_validators = {
        v.validator.pubkey: v for v in bunker.w3.cc.get_validators(blockstamp)[3:6]
    }

    result = bunker.is_abnormal_cl_rebase(blockstamp, frame_cl_rebase)

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
    bunker,
    mock_get_eth_distributed_events,
    mock_get_withdrawal_vault_balance,
    mock_get_validators,
    mock_get_first_non_missed_slot,
    blockstamp,
    expected_rebase
):
    bunker.last_report_ref_slot = 10
    bunker.c_conf = ChainConfig(
        slots_per_epoch=1,
        seconds_per_slot=12,
        genesis_time=0,
    )
    bunker.all_validators = {
        v.validator.pubkey: v for v in bunker.w3.cc.get_validators(blockstamp)
    }
    bunker.lido_validators = {
        v.validator.pubkey: v for v in bunker.w3.cc.get_validators(blockstamp)[3:6]
    }

    result = bunker._get_normal_cl_rebase(blockstamp)

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
    bunker,
    mock_get_eth_distributed_events,
    mock_get_withdrawal_vault_balance,
    mock_get_validators,
    mock_get_first_non_missed_slot,
    blockstamp,
    nearest_epoch_distance,
    far_epoch_distance,
    expected_is_negative,
):
    bunker.last_report_ref_slot = 0
    bunker.c_conf = ChainConfig(
        slots_per_epoch=1,
        seconds_per_slot=12,
        genesis_time=0,
    )
    bunker.b_conf.rebase_check_nearest_epoch_distance = nearest_epoch_distance
    bunker.b_conf.rebase_check_distant_epoch_distance = far_epoch_distance
    bunker.lido_validators = {
        v.validator.pubkey: v for v in bunker.w3.cc.get_validators(blockstamp)[3:6]
    }

    if isinstance(expected_is_negative, Exception):
        with pytest.raises(expected_is_negative.__class__, match=expected_is_negative.args[0]):
            bunker._is_negative_specific_cl_rebase(blockstamp)
    else:
        result = bunker._is_negative_specific_cl_rebase(blockstamp)
        assert result == expected_is_negative


@pytest.mark.unit
@pytest.mark.parametrize(
    ("prev_blockstamp", "curr_blockstamp", "expected_rebase"),
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
    bunker,
    mock_get_eth_distributed_events,
    mock_get_withdrawal_vault_balance,
    mock_get_validators,
    prev_blockstamp,
    curr_blockstamp,
    expected_rebase,
):

    bunker.lido_validators = {
        v.validator.pubkey: v for v in bunker.w3.cc.get_validators(curr_blockstamp)[3:6]
    }

    if isinstance(expected_rebase, Exception):
        with pytest.raises(expected_rebase.__class__, match=expected_rebase.args[0]):
            bunker._calculate_cl_rebase_between(prev_blockstamp, curr_blockstamp)
    else:
        result = bunker._calculate_cl_rebase_between(prev_blockstamp, curr_blockstamp)
        assert result == expected_rebase


@pytest.mark.unit
@pytest.mark.parametrize(
    ("from_block", "to_block", "expected_result"),
    [(0, 10, 1 * 10 ** 9), (10, 20, 0), (20, 30, ValueError("More than one ETHDistributed event found"))]
)
def test_get_withdrawn_from_vault_between(
    bunker, mock_get_eth_distributed_events, from_block, to_block, expected_result
):
    def b(block_number: int) -> BlockStamp:
        return ReferenceBlockStamp('', '', block_number, '', block_number, 0, block_number, 0)

    if isinstance(expected_result, Exception):
        with pytest.raises(expected_result.__class__, match=expected_result.args[0]):
            bunker._get_withdrawn_from_vault_between(b(from_block), b(to_block))
    else:
        result = bunker._get_withdrawn_from_vault_between(b(from_block), b(to_block))
        assert result == expected_result


# -- Statics --


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
    total_effective_balance = BunkerService.calculate_real_balance(validators)
    assert total_effective_balance == expected_balance


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
    slashed_validators = BunkerService.not_withdrawn_slashed_validators(validators, EpochNumber(15000))
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

    per_epoch_buckets = BunkerService.get_per_epoch_buckets(all_slashed_validators, EpochNumber(15000))

    assert len(per_epoch_buckets) == expected_buckets
    assert per_epoch_buckets[expected_determined_slashed_epoch] == all_slashed_validators
    for epoch in expected_possible_slashed_epochs:
        assert per_epoch_buckets[EpochNumber(epoch)] == {'0x1': all_slashed_validators['0x1']}


@pytest.mark.unit
def test_get_bounded_slashed_validators():
    determined_slashed_epoch = EpochNumber(10000)
    per_epoch_buckets = BunkerService.get_per_epoch_buckets(all_slashed_validators, EpochNumber(15000))

    bounded_slashed_validators = BunkerService.get_bound_slashed_validators(
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
    per_epoch_buckets = BunkerService.get_per_epoch_buckets(all_slashed_validators, EpochNumber(15000))

    per_epoch_lido_midterm_penalties = BunkerService.get_per_epoch_lido_midterm_penalties(
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
    per_epoch_buckets = BunkerService.get_per_epoch_buckets(all_slashed_validators, EpochNumber(15000))
    per_epoch_lido_midterm_penalties = BunkerService.get_per_epoch_lido_midterm_penalties(
       per_epoch_buckets, lido_slashed_validators, total_balance
    )

    per_frame_lido_midterm_penalties = BunkerService.get_per_frame_lido_midterm_penalties(
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
    frame_by_epoch = BunkerService.get_frame_by_epoch(epoch, frame_config)
    assert frame_by_epoch == expected_frame


@pytest.mark.unit
@pytest.mark.parametrize(
    ("epoch_passed", "mean_lido", "mean_total", "expected"),
    [(225, 32 * 152261 * 10 ** 9, 32 * 517310 * 10 ** 9, 490787204556),
     (450, 32 * 152261 * 10 ** 9, 32 * 517310 * 10 ** 9, 981574409112)]
)
def test_calculate_normal_cl_rebase(bunker, epoch_passed, mean_lido, mean_total, expected):
    normal_cl_rebase = bunker._calculate_normal_cl_rebase(epoch_passed, mean_lido, mean_total)
    assert normal_cl_rebase == expected
