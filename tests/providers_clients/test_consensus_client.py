"""Simple tests for the consensus client responses validity."""
import pytest

from src.providers.consensus.client import ConsensusClient, UnexpectedStateId
from src.providers.consensus.typings import Validator
from src.variables import CONSENSUS_CLIENT_URI


@pytest.fixture
def consensus_client():
    return ConsensusClient(CONSENSUS_CLIENT_URI)


@pytest.mark.integration
def test_get_block_root(consensus_client: ConsensusClient):
    block_root = consensus_client.get_block_root('head')
    assert len(block_root.root) == 66


@pytest.mark.integration
def test_get_block_details(consensus_client: ConsensusClient, web3):
    root = consensus_client.get_block_root('head').root
    block_details = consensus_client.get_block_details(root)
    assert block_details


@pytest.mark.integration
def test_get_validators(consensus_client: ConsensusClient):
    root = consensus_client.get_block_root('head').root
    details = consensus_client.get_block_details(root)
    validators: list[Validator] = consensus_client.get_validators(details.message.state_root)
    assert validators

    validator = validators[0]
    validator_by_pub_key = consensus_client.get_validators(details.message.state_root, pub_keys=validator.validator.pubkey)
    assert validator_by_pub_key[0] == validator


@pytest.mark.unit
def test_caching_issues(consensus_client):
    with pytest.raises(UnexpectedStateId):
        consensus_client.get_validators('head')
    with pytest.raises(UnexpectedStateId):
        consensus_client.get_block_details('finalized')
