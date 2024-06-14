# pyright: reportArgumentType=false

import re
from unittest.mock import Mock

import pytest

from src import variables
from src.providers.execution.exceptions import InconsistentEvents
from src.utils.events import get_events_in_past, get_events_in_range
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

        return list(filter(lambda e: fromBlock <= e['blockNumber'] <= toBlock, events))


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


@pytest.mark.unit
def test_get_events_in_range(caplog):
    variables.EVENTS_SEARCH_STEP = 2
    events = list(get_events_in_range(ContractEvent(), 10, 28))
    assert len(events) == 4

    log_regex = re.compile(r"events in range \[(\d+);(\d+)\]")
    assert log_regex.findall(caplog.text) == [
        ('10', '12'),
        ('13', '15'),
        ('16', '18'),
        ('19', '21'),
        ('22', '24'),
        ('25', '27'),
        ('28', '28'),
    ]


@pytest.mark.unit
def test_get_events_in_range_single_block(caplog):
    events = list(get_events_in_range(ContractEvent(), 25, 25))
    assert len(events) == 1
    assert "in range [25;25]" in caplog.text


@pytest.mark.unit
def test_get_events_in_range_invalid_range():
    with pytest.raises(ValueError, match="l_block=30 > r_block=10"):
        list(get_events_in_range(ContractEvent(), 30, 10))


@pytest.mark.unit
def test_get_events_in_range_inconsistent_events():
    event = ContractEvent()

    event.get_logs = Mock(return_value=[{"blockNumber": 100500}])
    with pytest.raises(InconsistentEvents):
        list(get_events_in_range(event, 10, 20))

    event.get_logs = Mock(return_value=[{"blockNumber": 1}])
    with pytest.raises(InconsistentEvents):
        list(get_events_in_range(event, 10, 20))
