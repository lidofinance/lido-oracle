import pytest

from unittest.mock import Mock
from src.typings import BlockStamp
from src.services.withdrawal import Withdrawal
from src.modules.submodules.consensus import ChainConfig, FrameConfig


@pytest.fixture()
def chain_config():
    return ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0)


@pytest.fixture()
def frame_config():
    return FrameConfig(initial_epoch=0, epochs_per_frame=10, fast_lane_length_slots=0)


@pytest.fixture()
def past_blockstamp():
    yield BlockStamp(
        ref_slot=4947936,
        ref_epoch=154623,
        block_root='0xfc3a63409fe5c53c3bb06a96fc4caa89011452835f767e64bf59f2b6864037cc',
        state_root='0x7fcd917cbe34f306989c40bd64b8e2057a39dfbfda82025549f3a44e6b2295fc',
        slot_number=4947936,
        block_number=8457825,
        block_hash='0x0d61eeb26e4cbb076e557ddb8de092a05e2cba7d251ad4a87b0826cf5926f87b',
        block_timestamp=0
    )

@pytest.fixture()
def subject(web3, past_blockstamp, chain_config, frame_config, contracts, keys_api_client, consensus_client):
    return Withdrawal(web3, past_blockstamp, chain_config, frame_config)


@pytest.mark.skip
def test_returns_zero_if_no_unfinalized_requests(subject):
    subject._has_unfinalized_requests = Mock(return_value=False)
    subject._get_available_eth = Mock(return_value=0)

    result = subject.get_next_last_finalizable_id(True, 100, 0, 0)

    assert result == 0


@pytest.mark.skip
def test_returns_last_finalizable_id(subject):
    subject._has_unfinalized_requests = Mock(return_value=True)
    subject._get_available_eth = Mock(return_value=100)

    subject.safe_border_service.get_safe_border_epoch = Mock(return_value=0)
    subject._fetch_last_finalizable_request_id = Mock(return_value=1)

    assert subject.get_next_last_finalizable_id(True, 100, 0, 0) == 1
