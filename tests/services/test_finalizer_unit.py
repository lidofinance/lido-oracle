import pytest

from unittest.mock import Mock
from src.services.finalizer import Finalizer

from src.typings import BlockStamp

@pytest.fixture()
def subject(web3, contracts, keys_api_client, consensus_client):
    return Finalizer(web3)

def test_returns_zero_if_no_unfinalized_requests(subject, past_blockstamp):
    subject._has_unfinalized_requests = Mock(return_value=False)
    subject._fetch_locked_ether_amount = Mock(return_value=0)

    result = subject.get_next_last_finalizable_id(True, 100, past_blockstamp)

    assert result == 0

def test_returns_last_finalizable_id(subject, past_blockstamp):
    subject._has_unfinalized_requests = Mock(return_value=True)
    subject._fetch_locked_ether_amount = Mock(return_value=100)

    subject.safe_border_service.get_safe_border_epoch = Mock(return_value=0)
    subject._fetch_last_finalizable_request_id = Mock(return_value=1)

    assert subject.get_next_last_finalizable_id(True, 100, past_blockstamp) == 1