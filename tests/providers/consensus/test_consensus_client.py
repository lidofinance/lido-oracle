# pylint: disable=protected-access
"""Simple tests for the consensus client responses validity."""

from unittest.mock import Mock

import pytest
import requests
from prometheus_client import CollectorRegistry
from prometheus_client.exposition import generate_latest
from web3_multi_provider import metrics as w3_metrics

import variables
from providers.consensus.client import ConsensusClient
from providers.consensus.types import Validator
from providers.http_provider import NotOkResponse
from tests.factory.blockstamp import BlockStampFactory
from type_aliases import EpochNumber, SlotNumber
from utils.blockstamp import build_blockstamp


@pytest.fixture
def consensus_client(request):
    params = getattr(request, 'param', {})
    rpc_endpoint = params.get('endpoint', variables.CONSENSUS_CLIENT_URI[0])
    return ConsensusClient([rpc_endpoint], 10)


# --- Unit tests for HTTPSessionManagerProxy integration ---


@pytest.mark.unit
def test_session_manager_init_params():
    client = ConsensusClient(['http://localhost:5051'], 30)
    sm = client._session_managers['http://localhost:5051']
    assert sm._chain_id == '1'
    assert sm._network == 'beacon'
    assert sm._layer == 'cl'
    assert sm._uri == 'http://localhost:5051'


@pytest.mark.unit
def test_session_manager_per_host():
    """One session_manager is created per host with the correct URI label."""
    client = ConsensusClient(['http://host1:5051', 'http://host2:5051'], 30)
    assert set(client._session_managers.keys()) == {'http://host1:5051', 'http://host2:5051'}
    assert client._session_managers['http://host1:5051']._uri == 'http://host1:5051'
    assert client._session_managers['http://host2:5051']._uri == 'http://host2:5051'


@pytest.mark.unit
def test_make_get_request_uses_session_manager_timed_call():
    """_make_get_request routes through the matching session_manager._timed_call."""
    client = ConsensusClient(['http://localhost:5051'], 30)
    mock_response = Mock()
    client._session_managers['http://localhost:5051']._timed_call = Mock(return_value=mock_response)

    result = client._make_get_request('http://localhost:5051', 'eth/v1/beacon/genesis', timeout=30)

    client._session_managers['http://localhost:5051']._timed_call.assert_called_once_with(
        client.session.get, 'http://localhost:5051/eth/v1/beacon/genesis', timeout=30
    )
    assert result is mock_response


@pytest.mark.unit
def test_make_get_request_uses_correct_session_manager_per_host():
    """Each fallback host uses its own session_manager for accurate metric labels."""
    client = ConsensusClient(['http://host1:5051', 'http://host2:5051'], 30)
    mock_response = Mock()
    client._session_managers['http://host1:5051']._timed_call = Mock(return_value=mock_response)
    client._session_managers['http://host2:5051']._timed_call = Mock(return_value=mock_response)

    client._make_get_request('http://host2:5051', 'eth/v1/beacon/genesis')

    client._session_managers['http://host1:5051']._timed_call.assert_not_called()
    client._session_managers['http://host2:5051']._timed_call.assert_called_once()


@pytest.mark.unit
def test_make_get_request_uses_provider_session():
    """_make_get_request passes self.session.get to _timed_call, preserving retry strategy."""
    client = ConsensusClient(['http://localhost:5051'], 30)
    mock_response = Mock()
    mock_response.status_code = 200
    client.session.get = Mock(return_value=mock_response)
    client._session_managers['http://localhost:5051']._timed_call = Mock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))

    client._make_get_request('http://localhost:5051', 'eth/v1/beacon/genesis')

    client.session.get.assert_called_once()


@pytest.mark.unit
def test_session_manager_metrics_recorded():
    """Verify that HTTPSessionManagerProxy writes metrics on each request."""
    registry = CollectorRegistry()
    w3_metrics.init_metrics(registry=registry)
    try:
        client = ConsensusClient(['http://localhost:5051'], 30)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        client.session.get = Mock(return_value=mock_response)
        client._make_get_request(
            'http://localhost:5051',
            'eth/v1/beacon/genesis',
            timeout=30,
        )

        output = generate_latest(registry).decode()

        # Counter incremented once with success labels
        assert 'http_rpc_requests_total{' in output
        assert 'result="success"' in output
        assert 'network="beacon"' in output
        assert 'layer="cl"' in output
        assert 'chain_id="1"' in output

        # Response time histogram observed
        assert 'http_rpc_response_seconds_count{' in output

        # Per-method CL path counter (normalized path used as method label)
        assert 'rpc_request_total{' in output
        assert 'method="/eth/v1/beacon/genesis"' in output
    finally:
        # Reset module-level metrics back to dummies so other tests are unaffected
        w3_metrics._HTTP_RPC_SERVICE_REQUESTS = w3_metrics._DummyMetric()
        w3_metrics._HTTP_RPC_BATCH_SIZE = w3_metrics._DummyMetric()
        w3_metrics._RPC_REQUEST = w3_metrics._DummyMetric()
        w3_metrics._RPC_SERVICE_RESPONSE_SECONDS = w3_metrics._DummyMetric()
        w3_metrics._RPC_SERVICE_REQUEST_PAYLOAD_BYTES = w3_metrics._DummyMetric()
        w3_metrics._RPC_SERVICE_RESPONSE_PAYLOAD_BYTES = w3_metrics._DummyMetric()


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
