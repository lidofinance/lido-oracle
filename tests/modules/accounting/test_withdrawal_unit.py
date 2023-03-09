import pytest

from hypothesis import given, strategies, settings, HealthCheck
from dataclasses import dataclass
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
def subject(
    web3,
    past_blockstamp,
    chain_config,
    frame_config,
    contracts,
    keys_api_client,
    consensus_client
):
    return Withdrawal(web3, past_blockstamp, chain_config, frame_config)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("is_paused", "has_unfinalized_requests", "expected_result"),
    [
        (False, True, 100),
        (False, False, 0),
        (True, True, 0)
    ]
)
def test_returns_zero_if_no_unfinalized_requests(
    subject: Withdrawal,
    is_paused: bool,
    has_unfinalized_requests: bool,
    expected_result: int,
):
    subject._fetch_is_paused = Mock(return_value=is_paused)
    subject._has_unfinalized_requests = Mock(return_value=has_unfinalized_requests)
    subject._get_available_eth = Mock(return_value=0)
    subject.safe_border_service.get_safe_border_epoch = Mock(return_value=0)
    subject._fetch_last_finalizable_request_id = Mock(return_value=expected_result)

    result = subject.get_next_last_finalizable_id(True, 100, 0, 0)

    assert result == expected_result


@pytest.mark.unit
@pytest.mark.parametrize(("last_finalized_id", "last_requested_id"), [(2, 1), (1, 1)])
def test_has_unfinalized_requests(subject: Withdrawal, last_finalized_id: int, last_requested_id: int):
    subject._fetch_last_finalized_request_id = Mock(return_value=last_finalized_id)
    subject._fetch_last_request_id = Mock(return_value=last_requested_id)

    assert subject._has_unfinalized_requests() == (last_finalized_id > last_requested_id)


@pytest.mark.unit
@given(strategies.lists(strategies.integers(min_value=0), min_size=4, max_size=4))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_get_available_eth(
    subject: Withdrawal,
    params: list[int]
):
    subject._fetch_buffered_ether = Mock(return_value=params[0])
    subject._fetch_unfinalized_steth = Mock(return_value=params[1])

    reserved_buffer = min(params[0], params[1])

    assert subject._get_available_eth(params[2], params[3]) == params[2] + params[3] + reserved_buffer
