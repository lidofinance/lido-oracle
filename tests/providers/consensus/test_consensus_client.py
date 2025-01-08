# pylint: disable=protected-access
"""Simple tests for the consensus client responses validity."""

from unittest.mock import Mock

import pytest

from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.types import Validator
from src.types import SlotNumber
from src.utils.blockstamp import build_blockstamp
from src.variables import CONSENSUS_CLIENT_URI
from tests.factory.blockstamp import BlockStampFactory


@pytest.fixture
def consensus_client():
    return ConsensusClient(CONSENSUS_CLIENT_URI, 5 * 60, 5, 5)


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
def test_get_block_attestations(consensus_client: ConsensusClient):
    root = consensus_client.get_block_root('finalized').root

    attestations = list(consensus_client.get_block_attestations(root))
    assert attestations


@pytest.mark.integration
def test_get_attestation_committees(consensus_client: ConsensusClient):
    root = consensus_client.get_block_root('finalized').root
    block_details = consensus_client.get_block_details(root)
    blockstamp = build_blockstamp(block_details)

    attestation_committees = list(consensus_client.get_attestation_committees(blockstamp))
    assert attestation_committees

    attestation_committee = attestation_committees[0]
    attestation_committee_by_slot = list(
        consensus_client.get_attestation_committees(blockstamp, slot=SlotNumber(int(attestation_committee.slot)))
    )
    assert attestation_committee_by_slot[0].slot == attestation_committee.slot
    assert attestation_committee_by_slot[0].index == attestation_committee.index
    assert str(attestation_committee_by_slot[0].validators) == str(attestation_committee.validators)


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


@pytest.mark.integration
@pytest.mark.skip(reason="Too long to complete in CI")
def test_get_state_view(consensus_client: ConsensusClient):
    state_view = consensus_client.get_state_view("head")
    assert state_view.slot > 0

    spec = consensus_client.get_config_spec()
    epoch = state_view.slot // 32
    if epoch >= int(spec.ELECTRA_FORK_EPOCH):
        assert state_view.earliest_exit_epoch != 0
        assert state_view.exit_balance_to_consume >= 0


@pytest.mark.unit
def test_get_returns_nor_dict_nor_list(consensus_client: ConsensusClient):
    consensus_client._get_without_fallbacks = Mock(return_value=(1, None))
    bs = BlockStampFactory.build()

    raises = pytest.raises(ValueError, match='Expected (mapping|list) response')

    with raises:
        consensus_client.get_config_spec()

    with raises:
        consensus_client.get_genesis()

    with raises:
        consensus_client.get_block_root('head')

    with raises:
        consensus_client.get_block_header(SlotNumber(0))

    with raises:
        consensus_client.get_block_details(SlotNumber(0))

    with raises:
        consensus_client.get_validators_no_cache(bs)

    with raises:
        consensus_client._get_validators_with_prysm(bs)

    with raises:
        consensus_client._get_chain_id_with_provider(0)
