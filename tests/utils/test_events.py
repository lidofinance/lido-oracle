# pyright: reportArgumentType=false

from unittest.mock import Mock

import pytest

from src import variables
from src.providers.execution.exceptions import InconsistentEvents
from src.utils.events import get_events_in_past, get_events_in_range
from tests.factory.blockstamp import ReferenceBlockStampFactory


@pytest.fixture()
def events():
    return [
        {'blockNumber': 10, 'args': {'timestamp': 10 * 10}},
        {'blockNumber': 15, 'args': {'timestamp': 15 * 10}},
        # 5 missed blocks
        {'blockNumber': 20, 'args': {'timestamp': 25 * 10}},
        {'blockNumber': 25, 'args': {'timestamp': 30 * 10}},
        {'blockNumber': 30, 'args': {'timestamp': 35 * 10}},
    ]


@pytest.fixture()
def contract_event(events):
    def get_logs(from_block, to_block):
        return [e for e in events if from_block <= e['blockNumber'] <= to_block]

    return Mock(get_logs=Mock(side_effect=get_logs))


@pytest.mark.unit
def test_get_contract_events_in_past(contract_event):
    seconds_per_slot = 10
    bs = ReferenceBlockStampFactory.build(
        slot_number=36,
        block_number=31,
        block_timestamp=36 * 10,
        ref_slot=36,
        ref_epoch=0,
    )

    events = get_events_in_past(contract_event, bs, 10, seconds_per_slot)
    assert len(events) == 2
    events = get_events_in_past(contract_event, bs, 15, seconds_per_slot)
    assert len(events) == 3
    # 1 block should be filtered by ts
    events = get_events_in_past(contract_event, bs, 20, seconds_per_slot)
    assert len(events) == 3
    events = get_events_in_past(contract_event, bs, 25, seconds_per_slot)
    assert len(events) == 4
    events = get_events_in_past(contract_event, bs, 31, seconds_per_slot)
    assert len(events) == 5


@pytest.mark.unit
def test_get_events_in_range(contract_event):
    variables.EVENTS_SEARCH_STEP = 2
    events = list(get_events_in_range(contract_event, 10, 28))
    assert len(events) == 4
    assert contract_event.get_logs.call_args_list == [
        ({'from_block': 10, 'to_block': 12},),
        ({'from_block': 13, 'to_block': 15},),
        ({'from_block': 16, 'to_block': 18},),
        ({'from_block': 19, 'to_block': 21},),
        ({'from_block': 22, 'to_block': 24},),
        ({'from_block': 25, 'to_block': 27},),
        ({'from_block': 28, 'to_block': 28},),
    ]


@pytest.mark.unit
def test_get_events_in_range_single_block(contract_event):
    events = list(get_events_in_range(contract_event, 25, 25))
    assert len(events) == 1
    assert contract_event.get_logs.call_args == ({'from_block': 25, 'to_block': 25},)


@pytest.mark.unit
def test_get_events_in_range_invalid_range():
    with pytest.raises(ValueError, match="l_block=30 > r_block=10"):
        list(get_events_in_range(Mock(), 30, 10))


@pytest.mark.unit
def test_get_events_in_range_inconsistent_events():
    event = Mock()

    event.get_logs = Mock(return_value=[{"blockNumber": 100500}])
    with pytest.raises(InconsistentEvents):
        list(get_events_in_range(event, 10, 20))

    event.get_logs = Mock(return_value=[{"blockNumber": 1}])
    with pytest.raises(InconsistentEvents):
        list(get_events_in_range(event, 10, 20))
