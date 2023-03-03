import pytest

from unittest.mock import Mock
from src.services.withdrawal import Withdrawal
from src.modules.submodules.consensus import ChainConfig, FrameConfig
from tests.conftest import get_blockstamp_by_state


@pytest.fixture()
def chain_config():
    return ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0)


@pytest.fixture()
def frame_config():
    return FrameConfig(initial_epoch=0, epochs_per_frame=10, fast_lane_length_slots=0)


@pytest.fixture()
def past_blockstamp(web3, consensus_client):
    return get_blockstamp_by_state(web3, 'finalized')


@pytest.fixture()
def subject(web3, past_blockstamp, chain_config, frame_config, contracts, keys_api_client, consensus_client):
    return Withdrawal(web3, past_blockstamp, chain_config, frame_config)


def test_returns_zero_if_no_unfinalized_requests(subject):
    subject._has_unfinalized_requests = Mock(return_value=False)
    subject._get_available_eth = Mock(return_value=0)

    result = subject.get_next_last_finalizable_id(True, 100, 0, 0)

    assert result == 0


def test_returns_last_finalizable_id(subject):
    subject._has_unfinalized_requests = Mock(return_value=True)
    subject._get_available_eth = Mock(return_value=100)

    subject.safe_border_service.get_safe_border_epoch = Mock(return_value=0)
    subject._fetch_last_finalizable_request_id = Mock(return_value=1)

    assert subject.get_next_last_finalizable_id(True, 100, 0, 0) == 1
