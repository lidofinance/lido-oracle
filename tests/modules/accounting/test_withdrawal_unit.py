import pytest

from unittest.mock import Mock
from src.services.withdrawal import Withdrawal
from src.modules.submodules.consensus import ChainConfig, FrameConfig
from src.constants import SHARE_RATE_PRECISION_E27
from src.modules.accounting.types import BatchState
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import OracleReportLimitsFactory


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
    state_initial = BatchState(remaining_eth_budget=100, finished=False, batches=[1] + [0] * 35, batches_length=1)
    state_final = BatchState(remaining_eth_budget=100, finished=True, batches=[2] + [0] * 35, batches_length=2)
    subject.w3.lido_contracts.withdrawal_queue_nft.calculate_finalization_batches = Mock(
        side_effect=[state_initial, state_final]
    )
    subject.w3.lido_contracts.withdrawal_queue_nft.max_batches_length = Mock(return_value=36)

    result = subject._calculate_finalization_batches(1, SHARE_RATE_PRECISION_E27, past_blockstamp.block_timestamp)

    assert result == [2]
