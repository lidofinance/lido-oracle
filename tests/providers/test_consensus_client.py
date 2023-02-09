import pytest

from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.typings import BlockRootResponse, BlockDetailsResponse, Validator
from src.variables import CONSENSUS_CLIENT_URI

pytestmarks = pytest.mark.integration


@pytest.fixture()
def consensus_client():
    return ConsensusClient(CONSENSUS_CLIENT_URI)


def test_get_block_root(consensus_client):
    block_root = consensus_client.get_block_root('head')
    assert block_root
    assert list(BlockRootResponse.__required_keys__) == list(block_root.keys())


def test_get_block_details(consensus_client):
    block_details = consensus_client.get_block_details('head')
    assert block_details
    assert BlockDetailsResponse.__required_keys__ == block_details.keys()


def test_get_validators(consensus_client):
    validators = consensus_client.get_validators('head')
    validator = validators[0]
    assert validators
    assert Validator.__required_keys__ == validators[0].keys()

    validator_by_pub_key = consensus_client.get_validators('head', pub_keys=validator['validator']['pubkey'])
    assert validator_by_pub_key[0] == validator
