# pylint: disable=protected-access
"""Simple tests for the consensus client responses validity."""

from unittest.mock import Mock

import pytest
import requests

from src import variables
from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.types import Validator
from src.providers.http_provider import NotOkResponse
from src.types import EpochNumber, SlotNumber
from src.utils.blockstamp import build_blockstamp
from tests.factory.blockstamp import BlockStampFactory


@pytest.fixture
def consensus_client(request):
    params = getattr(request, 'param', {})
    rpc_endpoint = params.get('endpoint', variables.CONSENSUS_CLIENT_URI)
    return ConsensusClient(rpc_endpoint, 10, 3, 3)


@pytest.mark.integration
@pytest.mark.testnet
def test_get_block_root(consensus_client: ConsensusClient):
    block_root = consensus_client.get_block_root('head')
    assert len(block_root.root) == 66


@pytest.mark.integration
@pytest.mark.testnet
def test_get_block_details(consensus_client: ConsensusClient, web3):
    root = consensus_client.get_block_root('head').root
    block_details = consensus_client.get_block_details(root)
    assert block_details


@pytest.mark.integration
@pytest.mark.testnet
def test_get_block_attestations_and_sync(consensus_client: ConsensusClient):
    root = consensus_client.get_block_root('finalized').root

    attestations_and_syncs = consensus_client.get_block_attestations_and_sync(root)
    assert attestations_and_syncs
    attestations, syncs = attestations_and_syncs
    assert attestations
    assert syncs


@pytest.mark.integration
@pytest.mark.testnet
def test_get_attestation_committees(consensus_client: ConsensusClient):
    root = consensus_client.get_block_root('finalized').root
    block_details = consensus_client.get_block_details(root)
    blockstamp = build_blockstamp(block_details)

    attestation_committees = list(consensus_client.get_attestation_committees(blockstamp))
    assert attestation_committees

    attestation_committee = attestation_committees[0]
    attestation_committee_by_slot = consensus_client.get_attestation_committees(
        blockstamp, slot=attestation_committee.slot
    )
    assert attestation_committee_by_slot[0].slot == attestation_committee.slot
    assert attestation_committee_by_slot[0].index == attestation_committee.index
    assert attestation_committee_by_slot[0].validators == attestation_committee.validators


@pytest.mark.integration
@pytest.mark.testnet
def test_get_sync_committee(consensus_client: ConsensusClient):
    root = consensus_client.get_block_root('finalized').root
    block_details = consensus_client.get_block_details(root)
    blockstamp = build_blockstamp(block_details)
    epoch = blockstamp.slot_number // 32

    sync_committee = consensus_client.get_sync_committee(blockstamp, epoch)
    assert sync_committee

    # Prysm error fallback
    consensus_client._get = Mock(
        side_effect=[
            NotOkResponse(status=404, text=consensus_client.PRYSM_STATE_NOT_FOUND_ERROR),
            (sync_committee.__dict__, "dummy_metadata"),
        ]
    )
    sync_committee = consensus_client.get_sync_committee(blockstamp, epoch)
    assert sync_committee


@pytest.mark.integration
@pytest.mark.testnet
def test_get_validators(consensus_client: ConsensusClient):
    root = consensus_client.get_block_root('finalized').root
    block_details = consensus_client.get_block_details(root)
    blockstamp = build_blockstamp(block_details)

    validators: list[Validator] = consensus_client.get_validators(blockstamp)
    assert validators

    validators_no_cache = consensus_client.get_validators_no_cache(blockstamp)
    assert validators_no_cache[42] == validators[42]


@pytest.mark.integration
@pytest.mark.testnet
def test_get_state_view(consensus_client: ConsensusClient):
    root = consensus_client.get_block_root('finalized').root
    block_details = consensus_client.get_block_details(root)
    blockstamp = build_blockstamp(block_details)

    state_view = consensus_client.get_state_view(blockstamp)
    assert state_view.slot == blockstamp.slot_number
    assert state_view.earliest_exit_epoch != 0
    assert state_view.exit_balance_to_consume >= 0


@pytest.mark.unit
def test_get_returns_nor_dict_nor_list(consensus_client: ConsensusClient):
    resp = requests.Response()
    resp.status_code = 200
    resp._content = b'{"data": 1}'

    consensus_client.session.get = Mock(return_value=resp)
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
        consensus_client.get_block_attestations_and_sync(SlotNumber(0))

    with raises:
        consensus_client.get_attestation_committees(bs)

    with raises:
        consensus_client.get_sync_committee(bs, EpochNumber(0))

    with raises:
        consensus_client.get_proposer_duties(EpochNumber(0), Mock())

    with raises:
        consensus_client.get_state_block_roots(SlotNumber(0))

    with raises:
        consensus_client.get_state_view_no_cache(bs)

    with raises:
        consensus_client.get_validators_no_cache(bs)

    with raises:
        consensus_client._get_chain_id_with_provider(0)


@pytest.mark.unit
def test_get_proposer_duties_fails_on_root_check(consensus_client: ConsensusClient):
    resp = requests.Response()
    resp.status_code = 200
    resp._content = b'{"data": [], "dependent_root": "0x01"}'

    consensus_client.session.get = Mock(return_value=resp)

    with pytest.raises(ValueError, match="Dependent root for proposer duties request mismatch"):
        consensus_client.get_proposer_duties(EpochNumber(0), "0x02")
