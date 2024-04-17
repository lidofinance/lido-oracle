import pytest

from src.types import ReferenceBlockStamp
from src.utils.events import get_events_in_past
from tests.factory.blockstamp import ReferenceBlockStampFactory


class ContractEvent:
    def get_logs(self, fromBlock, toBlock):
        events = [
            {'blockNumber': 10, 'args': {'timestamp': 10 * 10}},
            {'blockNumber': 15, 'args': {'timestamp': 15 * 10}},
            # 5 missed blocks
            {'blockNumber': 20, 'args': {'timestamp': 25 * 10}},
            {'blockNumber': 25, 'args': {'timestamp': 30 * 10}},
            {'blockNumber': 30, 'args': {'timestamp': 35 * 10}},
        ]

        return list(filter(lambda e: fromBlock < e['blockNumber'] < toBlock, events))


@pytest.mark.unit
@pytest.mark.possible_integration
def test_get_contract_events_in_past():
    seconds_per_slot = 10
    bs = ReferenceBlockStampFactory.build(
        slot_number=36,
        block_number=31,
        block_timestamp=36 * 10,
        ref_slot=36,
        ref_epoch=0,
    )

    events = get_events_in_past(ContractEvent(), bs, 10, seconds_per_slot)
    assert len(events) == 2
    events = get_events_in_past(ContractEvent(), bs, 15, seconds_per_slot)
    assert len(events) == 3
    # 1 block should be filtered by ts
    events = get_events_in_past(ContractEvent(), bs, 20, seconds_per_slot)
    assert len(events) == 3
    events = get_events_in_past(ContractEvent(), bs, 25, seconds_per_slot)
    assert len(events) == 4
    events = get_events_in_past(ContractEvent(), bs, 31, seconds_per_slot)
    assert len(events) == 5
