"""Simple tests for the consensus client responses validity."""
import pytest

from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.typings import Validator
from src.variables import CONSENSUS_CLIENT_URI

pytestmark = pytest.mark.integration


@pytest.fixture()
def consensus_client():
    return ConsensusClient(CONSENSUS_CLIENT_URI)


def test_get_block_root(consensus_client):
    block_root = consensus_client.get_block_root('head')
    assert len(block_root.root) == 66


def test_get_block_details(consensus_client):
    block_details = consensus_client.get_block_details('head')
    assert block_details


def test_get_validators(consensus_client):
    validators: list[Validator] = consensus_client.get_validators('head')
    assert validators

    validator = validators[0]
    validator_by_pub_key = consensus_client.get_validators('head', pub_keys=validator.validator.pubkey)
    assert validator_by_pub_key[0] == validator
