import pytest

from src.services.withdrawal import Withdrawal

@pytest.fixture()
def subject(web3, contracts, keys_api_client, consensus_client):
    return Withdrawal(web3)

@pytest.mark.skip(reason="waiting for testnet deployment")
def test_returns_none_if_no_unfinalized_requests(subject, past_blockstamp):
    pass
