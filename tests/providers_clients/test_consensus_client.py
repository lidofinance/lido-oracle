"""Simple tests for the consensus client responses validity."""
import pytest

from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.typings import Validator
from src.utils.blockstamp import build_blockstamp
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
    root = consensus_client.get_block_root('finalized').root
    block_details = consensus_client.get_block_details(root)
    blockstamp = build_blockstamp(block_details)

    validators: list[Validator] = consensus_client.get_validators(blockstamp)
    assert validators

    validator = validators[0]
    validator_by_pub_key = consensus_client.get_validators_no_cache(blockstamp, pub_keys=validator.validator.pubkey)
    assert validator_by_pub_key[0] == validator
