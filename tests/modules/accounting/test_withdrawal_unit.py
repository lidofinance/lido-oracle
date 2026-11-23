from unittest.mock import Mock

import pytest

from src.modules.common.types import ChainConfig, FrameConfig
from src.modules.oracles.accounting.types import BatchState
from src.services.withdrawal import Withdrawal
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import OracleReportLimitsFactory
from tests.modules.accounting.withdrawal_queue_model import WithdrawalQueueModel


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

    result = subject._calculate_finalization_batches(1, 1000, past_blockstamp.block_timestamp)

    assert result == [2]


@pytest.mark.unit
def test__calculate_finalization_batches__budget_within_rounding_reserve__does_not_call_contract(
    subject: Withdrawal, past_blockstamp
):
    wq = subject.w3.lido_contracts.withdrawal_queue_nft
    wq.get_last_finalized_request_id = Mock(return_value=0)
    wq.get_last_request_id = Mock(return_value=3)
    wq.max_batches_length = Mock(return_value=36)
    wq.calculate_finalization_batches = Mock()

    result = subject._calculate_finalization_batches(1, 6, past_blockstamp.block_timestamp)

    wq.calculate_finalization_batches.assert_not_called()
    assert result == []


def _total_claims(queue: WithdrawalQueueModel, last_id: int, share_rate: int) -> int:
    return sum(queue.claimable(request_id, share_rate) for request_id in range(1, last_id + 1))


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
