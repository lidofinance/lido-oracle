import pytest

from unittest.mock import Mock
from src.services.finalizer import Finalizer

from src.typings import BlockStamp

@pytest.fixture()
def blockstamp():
    return BlockStamp(
        block_root='0xf03b8bd6379c89654ad313d98284eda8d9cf2ab78dfb509e3b5d0dbe30f6d95c', 
        state_root='0x7818f12273c299881370ade970fd380f232e214e1ad59288feed34cc4322f551', 
        slot_number=106624, block_hash='0xd9dd59d7e631c998a5d89aba0358d17f8d89f545d3307627fc77fe63eb98d7d9',
        block_number=101593
    )

@pytest.fixture()
def subject(web3, contracts, keys_api_client, consensus_client):
    return Finalizer(web3)

def test_returns_none_if_no_unfinalized_requests(subject, blockstamp):
    subject._get_unfinalized_withdrawal_ids = Mock(return_value=(5, 5))

    result = subject.get_withdrawable_requests(True, 100, blockstamp)

    assert result == None

def test_returns_empty_list_if_no_withdrawable_requests(subject, blockstamp):
    subject._get_unfinalized_withdrawal_ids = Mock(return_value=(5, 10))
    subject._fetch_last_finalizable_request_id_by_budget = Mock(return_value=0)
    subject._fetch_last_finalizable_request_id_by_timestamp = Mock(return_value=6)
    subject.safe_border_service.get_safe_border_epoch = Mock(return_value=0)

    result = subject.get_withdrawable_requests(True, 100, blockstamp)

    assert result == None

def test_returns_list_of_withdrawable_requests(subject, blockstamp):
    subject._get_unfinalized_withdrawal_ids = Mock(return_value=(5, 10))
    subject._fetch_last_finalizable_request_id_by_budget = Mock(return_value=8)
    subject._fetch_last_finalizable_request_id_by_timestamp = Mock(return_value=7)
    subject.safe_border_service.get_safe_border_epoch = Mock(return_value=0)

    result = subject.get_withdrawable_requests(True, 100, blockstamp)

    assert result == [5, 6, 7]