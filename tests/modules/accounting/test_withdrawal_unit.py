from unittest.mock import Mock

import pytest

from src.modules.common.types import ChainConfig, FrameConfig
from src.modules.oracles.accounting.types import BatchState
from src.services.withdrawal import Withdrawal
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import OracleReportLimitsFactory
from tests.modules.accounting.withdrawal_queue_model import MAX_BATCHES_LENGTH, WithdrawalQueueModel


@pytest.fixture
def chain_config():
    return ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0)


@pytest.fixture
def frame_config():
    return FrameConfig(initial_epoch=0, epochs_per_frame=10, fast_lane_length_slots=0)


@pytest.fixture
def past_blockstamp(web3):
    return ReferenceBlockStampFactory.build()


@pytest.fixture
def subject(web3, past_blockstamp, chain_config, frame_config):
    web3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits = Mock(
        return_value=OracleReportLimitsFactory.build()
    )
    return Withdrawal(web3, past_blockstamp, chain_config, frame_config)


@pytest.mark.unit
def test_returns_empty_batch_if_there_is_no_requests(subject: Withdrawal):
    subject._has_unfinalized_requests = Mock(return_value=False)
    subject.w3.lido_contracts.withdrawal_queue_nft.is_paused.return_value = False

    result = subject.get_finalization_batches(True, 100, 0, 0)

    subject.w3.lido_contracts.withdrawal_queue_nft.is_paused.assert_called_once_with(subject.blockstamp.block_hash)
    assert result == []


@pytest.mark.unit
def test_returns_empty_batch_if_paused(subject: Withdrawal):
    subject.w3.lido_contracts.withdrawal_queue_nft.is_paused.return_value = True
    result = subject.get_finalization_batches(True, 100, 0, 0)

    subject.w3.lido_contracts.withdrawal_queue_nft.is_paused.assert_called_once_with(subject.blockstamp.block_hash)
    assert result == []


@pytest.mark.unit
def test_returns_batch_if_there_are_finalizable_requests(subject: Withdrawal):
    subject.w3.lido_contracts.withdrawal_queue_nft.is_paused.return_value = False
    subject._has_unfinalized_requests = Mock(return_value=True)
    subject._get_available_eth = Mock(return_value=100)

    subject.safe_border_service.get_safe_border_epoch = Mock(return_value=0)
    subject._calculate_finalization_batches = Mock(return_value=[1, 2, 3])

    result = subject.get_finalization_batches(True, 100, 0, 0)

    subject.w3.lido_contracts.withdrawal_queue_nft.is_paused.assert_called_once_with(subject.blockstamp.block_hash)
    assert result == [1, 2, 3]


@pytest.mark.unit
def test_no_available_eth_to_cover_wc(subject: Withdrawal):
    subject.w3.lido_contracts.withdrawal_queue_nft.is_paused = Mock(return_value=False)
    subject._has_unfinalized_requests = Mock(return_value=True)
    subject._get_available_eth = Mock(return_value=0)

    result = subject.get_finalization_batches(False, 100, 0, 0)

    subject.w3.lido_contracts.withdrawal_queue_nft.is_paused.assert_called_once_with(subject.blockstamp.block_hash)
    assert result == []


@pytest.mark.unit
def test_calculate_finalization_batches(subject: Withdrawal, past_blockstamp):
    wq = subject.w3.lido_contracts.withdrawal_queue_nft
    wq.get_last_finalized_request_id = Mock(return_value=0)
    wq.get_last_request_id = Mock(return_value=2)
    state_initial = BatchState(remaining_eth_budget=100, finished=False, batches=[1] + [0] * 35, batches_length=1)
    state_final = BatchState(remaining_eth_budget=100, finished=True, batches=[2] + [0] * 35, batches_length=2)
    wq.calculate_finalization_batches = Mock(side_effect=[state_initial, state_final])
    wq.max_batches_length = Mock(return_value=36)
    wq.prefinalize = Mock(return_value=1000 - 4 - 100)

    result = subject._calculate_finalization_batches(1, 1000, past_blockstamp.block_timestamp)

    assert result == [2]


@pytest.mark.unit
def test__calculate_finalization_batches__budget_within_rounding_reserve__does_not_call_contract(
    subject: Withdrawal, past_blockstamp
):
    wq = subject.w3.lido_contracts.withdrawal_queue_nft
    wq.get_last_finalized_request_id = Mock(return_value=0)
    wq.get_last_request_id = Mock(return_value=3)
    wq.calculate_finalization_batches = Mock()

    result = subject._calculate_finalization_batches(1, 6, past_blockstamp.block_timestamp)

    wq.calculate_finalization_batches.assert_not_called()
    assert result == []


ALICE_RATE = (1_273_762_593, 1_000_000_000)
BOB_RATE = (1_273_558_902, 1_000_000_000)
SIMULATED_SHARE_RATE = 1_273_660_747 * 10**18
LARGE_BUDGET = 10**24


def _total_claims(queue: WithdrawalQueueModel, last_id: int, share_rate: int) -> int:
    return sum(queue.claimable(request_id, share_rate) for request_id in range(1, last_id + 1))


def _discounted_then_nominal_queue(dust_request: bool) -> WithdrawalQueueModel:
    queue = WithdrawalQueueModel()
    queue.on_oracle_report(1)
    for _ in range(2):
        queue.request(1000 * 10**18, *ALICE_RATE)
    # The share rate drops with this report: Alice's requests end up above the next simulated rate, Bob's below it.
    queue.on_oracle_report(2)
    if dust_request:
        queue.request(100, *BOB_RATE)
    for _ in range(6):
        queue.request(1000 * 10**18, *BOB_RATE)
    return queue


@pytest.mark.unit
def test_calculate_finalization_batches__discounted_and_nominal_periods__keeps_view_batches(subject: Withdrawal):
    # Arrange
    queue = _discounted_then_nominal_queue(dust_request=False)
    subject.w3.lido_contracts.withdrawal_queue_nft = queue

    # Act
    batches = subject._calculate_finalization_batches(SIMULATED_SHARE_RATE, LARGE_BUDGET, 0)

    # Assert
    assert batches == [2, 8]
    assert queue.prefinalize(batches, SIMULATED_SHARE_RATE, None) - _total_claims(queue, 8, SIMULATED_SHARE_RATE) <= 1


@pytest.mark.unit
def test_calculate_finalization_batches__dust_request_bridges_discounted_and_nominal__splits_mixed_batch(
    subject: Withdrawal,
):
    # Arrange — the 100 wei request is above the rate by its own rounding, so the view joins it to Alice's
    # discounted requests and, by report timestamp, to Bob's nominal ones
    queue = _discounted_then_nominal_queue(dust_request=True)
    subject.w3.lido_contracts.withdrawal_queue_nft = queue
    assert queue.prefinalize([9], SIMULATED_SHARE_RATE, None) - _total_claims(queue, 9, SIMULATED_SHARE_RATE) > 10**17

    # Act
    batches = subject._calculate_finalization_batches(SIMULATED_SHARE_RATE, LARGE_BUDGET, 0)

    # Assert — every request is still finalized, and the lock matches what the claims pay out
    assert batches == [3, 9]
    assert queue.prefinalize(batches, SIMULATED_SHARE_RATE, None) - _total_claims(queue, 9, SIMULATED_SHARE_RATE) <= 2


@pytest.mark.unit
def test_calculate_finalization_batches__budget_spent_to_the_wei__lock_fits_available_eth(subject: Withdrawal):
    # Arrange — each 100 wei request is debited at 99 wei, while the batch is locked at its nominal 100 wei
    queue = WithdrawalQueueModel()
    pooled_ether, shares = 127, 100
    for _ in range(4):
        queue.request(100, pooled_ether, shares)
    queue.request(127 * 149_606_299_212_598_425, pooled_ether, shares)
    share_rate = 1_270_100_000 * 10**18
    subject.w3.lido_contracts.withdrawal_queue_nft = queue
    available_eth = _total_claims(queue, 5, share_rate)
    assert queue.prefinalize([5], share_rate, None) > available_eth

    # Act
    batches = subject._calculate_finalization_batches(share_rate, available_eth, 0)

    # Assert
    assert batches
    assert queue.prefinalize(batches, share_rate, None) <= available_eth


@pytest.mark.unit
def test_split_mixed_batches__more_batches_than_the_queue_accepts__keeps_the_first_ones(subject: Withdrawal):
    # Arrange — discounted and nominal requests alternate within one report period, so each one is its own batch
    queue = WithdrawalQueueModel()
    for _ in range(40):
        queue.request(1000 * 10**18, *ALICE_RATE)
        queue.request(1000 * 10**18, *BOB_RATE)
    subject.w3.lido_contracts.withdrawal_queue_nft = queue

    # Act
    batches = subject._split_mixed_batches([80], SIMULATED_SHARE_RATE, 0, MAX_BATCHES_LENGTH)

    # Assert
    assert batches == list(range(1, MAX_BATCHES_LENGTH + 1))
