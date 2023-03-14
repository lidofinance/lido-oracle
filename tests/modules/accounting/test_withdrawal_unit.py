import pytest

from unittest.mock import Mock
from src.services.withdrawal import Withdrawal
from src.modules.submodules.consensus import ChainConfig, FrameConfig
from tests.conftest import get_blockstamp_by_state
from src.constants import SHARE_RATE_PRECISION_E27
from src.modules.accounting.typings import BatchState


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
    # web3.lido_contracts.oracle_report_sanity_checker.functions.getOracleReportLimits().call = Mock(return_value=0)
    return Withdrawal(web3, past_blockstamp, chain_config, frame_config)


@pytest.mark.unit
def test_returns_empty_batch_if_there_is_no_requests(subject: Withdrawal):
    subject._has_unfinalized_requests = Mock(return_value=False)
    result = subject.get_finalization_batches(True, 100, 0, 0)

    assert result == []


@pytest.mark.unit
def test_returns_batch_if_there_are_finalizable_requests(subject: Withdrawal):
    subject._has_unfinalized_requests = Mock(return_value=True)
    subject._get_available_eth = Mock(return_value=100)

    subject.safe_border_service.get_safe_border_epoch = Mock(return_value=0)
    subject._calculate_finalization_batches = Mock(return_value=[1, 2, 3])

    assert subject.get_finalization_batches(True, 100, 0, 0) == [1, 2, 3]


@pytest.mark.unit
def test_calculate_finalization_batches(subject: Withdrawal, past_blockstamp):
    state_initial = BatchState(
        remaining_eth_budget=100,
        finished=False,
        batches=[1] + [0] * 35,
        batches_length=1
    )
    state_final = BatchState(
        remaining_eth_budget=100,
        finished=True,
        batches=[2] + [0] * 35,
        batches_length=2
    )
    subject._fetch_finalization_batches = Mock(side_effect=[state_initial, state_final])

    result = subject._calculate_finalization_batches(
        1,
        SHARE_RATE_PRECISION_E27,
        past_blockstamp.block_timestamp
    )

    assert result == [1, 2]
