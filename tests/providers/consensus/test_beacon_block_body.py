import pytest

from src.providers.consensus.types import BeaconBlockBody, ExecutionPayload, SignedExecutionPayloadBid
from src.providers.execution.exceptions import InconsistentData


SYNC_AGGREGATE = {'sync_committee_bits': '0x00'}
PAYLOAD = {'parent_hash': '0x01', 'block_hash': '0x02', 'block_number': '7', 'timestamp': '9'}
BID = {'message': {'parent_block_hash': '0x03'}}


@pytest.mark.unit
class TestBeaconBlockBody:
    def test_from_response__payload_and_bid_objects__parsed_into_dataclasses(self):
        # Act
        body = BeaconBlockBody.from_response(
            attestations=[],
            sync_aggregate=SYNC_AGGREGATE,
            execution_payload=PAYLOAD,
            signed_execution_payload_bid=BID,
        )

        # Assert
        assert isinstance(body.execution_payload, ExecutionPayload)
        assert body.execution_payload.block_number == 7
        assert isinstance(body.signed_execution_payload_bid, SignedExecutionPayloadBid)
        assert body.signed_execution_payload_bid.message.parent_block_hash == '0x03'

    def test_from_response__fields_absent__left_none(self):
        # Act
        body = BeaconBlockBody.from_response(attestations=[], sync_aggregate=SYNC_AGGREGATE)

        # Assert
        assert body.execution_payload is None
        assert body.signed_execution_payload_bid is None

    @pytest.mark.parametrize('field', ['execution_payload', 'signed_execution_payload_bid'])
    @pytest.mark.parametrize('value', ['0x03', [], 0])
    def test_from_response__field_neither_object_nor_null__raises_inconsistent_data(self, field, value):
        # Act / Assert
        with pytest.raises(InconsistentData, match=field):
            BeaconBlockBody.from_response(attestations=[], sync_aggregate=SYNC_AGGREGATE, **{field: value})
