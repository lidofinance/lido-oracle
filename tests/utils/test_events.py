# pyright: reportArgumentType=false

from unittest.mock import Mock

import pytest

from src import variables
from src.modules.common.types import ChainConfig
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
    chain_config = ChainConfig(slots_per_epoch=32, seconds_per_slot=10, genesis_time=0)
    bs = ReferenceBlockStampFactory.build(
        slot_number=36,
        block_number=31,
        block_timestamp=36 * 10,
        ref_slot=36,
        ref_epoch=0,
    )

    events = get_events_in_past(contract_event, bs, 10, chain_config)
    assert len(events) == 2
    events = get_events_in_past(contract_event, bs, 15, chain_config)
    assert len(events) == 3
    # 1 block should be filtered by ts
    events = get_events_in_past(contract_event, bs, 20, chain_config)
    assert len(events) == 3
    events = get_events_in_past(contract_event, bs, 25, chain_config)
    assert len(events) == 4
    events = get_events_in_past(contract_event, bs, 31, chain_config)
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


@pytest.mark.unit
class TestGetEventsInPastCutoff:
    """The cutoff is the reference slot's time, not the slot the blockstamp physically stands on.

    Under EIP-7732 a report blockstamp is built from the reference slot's child, so `slot_number`
    runs ahead of `ref_slot` while the execution anchor stays at the reference slot's own payload.
    """

    CHAIN_CONFIG = ChainConfig(slots_per_epoch=32, seconds_per_slot=10, genesis_time=0)

    @staticmethod
    def _event_at(block_number: int, timestamp: int) -> Mock:
        """A contract event mock that honours the queried block range, as the real one does."""
        log = {'blockNumber': block_number, 'args': {'timestamp': timestamp}}

        def get_logs(from_block, to_block):
            return [log] if from_block <= block_number <= to_block else []

        return Mock(get_logs=Mock(side_effect=get_logs))

    @pytest.fixture()
    def boundary_event(self):
        # ref_slot 63, ten-slot window -> cutoff at slot 53, i.e. timestamp 530.
        return self._event_at(60, 525)

    def test_get_events_in_past__immediate_child__event_before_cutoff_excluded(self, boundary_event):
        # Arrange
        bs = ReferenceBlockStampFactory.build(
            ref_slot=63, ref_epoch=0, slot_number=64, block_number=63, block_timestamp=630
        )

        # Act
        events = get_events_in_past(boundary_event, bs, 10, self.CHAIN_CONFIG)

        # Assert
        assert events == []

    def test_get_events_in_past__missed_children__event_before_cutoff_still_excluded(self, boundary_event):
        # Arrange: the child is four slots after the reference slot.
        bs = ReferenceBlockStampFactory.build(
            ref_slot=63, ref_epoch=0, slot_number=67, block_number=63, block_timestamp=630
        )

        # Act
        events = get_events_in_past(boundary_event, bs, 10, self.CHAIN_CONFIG)

        # Assert
        assert events == []

    def test_get_events_in_past__pre_fork_missed_ref_slot__cutoff_unchanged(self, boundary_event):
        # Arrange: pre-EIP-7732 the blockstamp falls back to the last non-missed slot before ref_slot.
        bs = ReferenceBlockStampFactory.build(
            ref_slot=63, ref_epoch=0, slot_number=60, block_number=60, block_timestamp=600
        )

        # Act
        events = get_events_in_past(boundary_event, bs, 10, self.CHAIN_CONFIG)

        # Assert
        assert events == []

    def test_get_events_in_past__event_exactly_at_cutoff__excluded(self):
        # Arrange: the filter is strictly greater than the cutoff.
        contract_event = self._event_at(60, 530)
        bs = ReferenceBlockStampFactory.build(
            ref_slot=63, ref_epoch=0, slot_number=64, block_number=63, block_timestamp=630
        )

        # Act
        events = get_events_in_past(contract_event, bs, 10, self.CHAIN_CONFIG)

        # Assert
        assert events == []

    def test_get_events_in_past__event_just_after_cutoff__included(self):
        # Arrange
        contract_event = self._event_at(60, 531)
        bs = ReferenceBlockStampFactory.build(
            ref_slot=63, ref_epoch=0, slot_number=64, block_number=63, block_timestamp=630
        )

        # Act
        events = get_events_in_past(contract_event, bs, 10, self.CHAIN_CONFIG)

        # Assert
        assert len(events) == 1

    def test_get_events_in_past__anchor_at_or_before_cutoff__returns_empty(self):
        # Arrange: a withheld reference-slot payload leaves the anchor further back than the window.
        contract_event = self._event_at(40, 400)
        bs = ReferenceBlockStampFactory.build(
            ref_slot=63, ref_epoch=0, slot_number=64, block_number=40, block_timestamp=400
        )

        # Act
        events = get_events_in_past(contract_event, bs, 10, self.CHAIN_CONFIG)

        # Assert
        assert events == []
        contract_event.get_logs.assert_not_called()
