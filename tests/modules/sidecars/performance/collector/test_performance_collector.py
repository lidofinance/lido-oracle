from datetime import UTC, datetime
from typing import cast
from unittest.mock import Mock, call, patch

import pytest

import src.modules.sidecars.performance.collector.collector as collector_module
from src.modules.common.types import ModuleExecuteDelay
from src.modules.sidecars.performance.collector.checkpoint import FrameCheckpointsIterator
from src.modules.sidecars.performance.collector.collector import PerformanceCollector
from src.modules.sidecars.performance.common.db import DutiesDB, EpochsDemand
from src.types import EpochNumber


UPDATED_AT = None

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime(2026, 1, 2, tzinfo=UTC)


@pytest.fixture
def mock_w3() -> Mock:
    """Mock Web3 instance"""
    return Mock()


@pytest.fixture
def mock_db() -> Mock:
    """Mock DutiesDB instance"""
    return Mock(spec=DutiesDB)


@pytest.fixture
def performance_collector(mock_w3: Mock, mock_db: Mock) -> PerformanceCollector:
    """Create PerformanceCollector instance with mocked dependencies"""
    with patch.object(collector_module, 'DutiesDB', return_value=mock_db):
        mock_db.get_epochs_demands_max_updated_at.return_value = T0
        mock_db.demands_count.return_value = 0
        collector = PerformanceCollector(mock_w3)
        return collector


class TestDefineEpochsToProcessRange:
    """Test cases for define_epochs_to_process_range method"""

    @pytest.mark.unit
    def test_empty_db_default_range(self, performance_collector: PerformanceCollector, mock_db: Mock):
        """Test when database is empty - should return default range"""
        finalized_epoch = EpochNumber(100)

        # Setup empty DB
        mock_db.min_epoch.return_value = None
        mock_db.max_epoch.return_value = None
        mock_db.get_epochs_demands.return_value = []
        mock_db.missing_epochs_in.return_value = [98]

        result = performance_collector._define_epochs_to_process_range(finalized_epoch)

        # Expected calculations:
        # max_available_epoch_to_check = 100 - 2 = 98
        # start_epoch = 98 (from missing_epochs_in)
        # end_epoch = 98
        assert result == (EpochNumber(98), EpochNumber(98))

    @pytest.mark.unit
    def test_finalized_epoch_less_than_checkpoint_delay_returns_none(
        self, performance_collector: PerformanceCollector, mock_db: Mock
    ):
        """Test when finalized epoch is below checkpoint required delay gap."""
        finalized_epoch = EpochNumber(FrameCheckpointsIterator.CHECKPOINT_SLOT_DELAY_EPOCHS - 1)

        # Setup empty DB
        mock_db.min_epoch.return_value = None
        mock_db.max_epoch.return_value = None
        mock_db.get_epochs_demands.return_value = []

        result = performance_collector._define_epochs_to_process_range(finalized_epoch)

        # max_available_epoch_to_check = 1 - 2 = -1 < 0
        assert result is None

    @pytest.mark.unit
    def test_db_with_gap_and_no_current_demands_process_missing_epochs(
        self, performance_collector: PerformanceCollector, mock_db: Mock
    ):
        """Test when there's a gap in the database and no current demands"""
        finalized_epoch = EpochNumber(100)

        # Setup DB with gap
        mock_db.min_epoch.return_value = 10
        mock_db.max_epoch.return_value = 90
        mock_db.get_epochs_demands.return_value = []
        mock_db.missing_epochs_in.return_value = [50, 51, 98]

        result = performance_collector._define_epochs_to_process_range(finalized_epoch)

        mock_db.missing_epochs_in.assert_called_once_with(10, 98)

        # Should start from the first missing epoch
        assert result == (EpochNumber(50), EpochNumber(98))

    @pytest.mark.unit
    def test_db_min_epoch_zero_is_used_as_start(self, performance_collector: PerformanceCollector, mock_db: Mock):
        finalized_epoch = EpochNumber(100)

        mock_db.min_epoch.return_value = 0
        mock_db.max_epoch.return_value = 90
        mock_db.get_epochs_demands.return_value = []
        mock_db.missing_epochs_in.return_value = [0, 1, 2]

        result = performance_collector._define_epochs_to_process_range(finalized_epoch)

        mock_db.missing_epochs_in.assert_called_once_with(0, 98)
        assert result == (EpochNumber(0), EpochNumber(98))

    @pytest.mark.unit
    def test_db_with_gap_process_missing_epochs(self, performance_collector: PerformanceCollector, mock_db: Mock):
        """Test when there's a gap in the database"""
        finalized_epoch = EpochNumber(100)

        # Setup DB with gap
        mock_db.min_epoch.return_value = 10
        mock_db.max_epoch.return_value = 90
        mock_db.get_epochs_demands.return_value = [EpochsDemand(consumer="test", from_epoch=10, to_epoch=90)]
        mock_db.is_range_available.return_value = False
        mock_db.missing_epochs_in.return_value = [50, 51, 52]

        result = performance_collector._define_epochs_to_process_range(finalized_epoch)

        mock_db.is_range_available.assert_called_once_with(10, 90)
        mock_db.missing_epochs_in.assert_called_once_with(10, 98)

        # Should start from the first missing epoch
        assert result == (EpochNumber(50), EpochNumber(98))

    @pytest.mark.unit
    def test_db_without_gap_continues_from_last(self, performance_collector: PerformanceCollector, mock_db: Mock):
        """Test when DB has no gaps - should collect next epochs"""
        finalized_epoch = EpochNumber(100)

        # Setup DB without gaps
        mock_db.min_epoch.return_value = 10
        mock_db.max_epoch.return_value = 90
        mock_db.get_epochs_demands.return_value = []
        # No missing epochs in the range
        mock_db.missing_epochs_in.return_value = []

        result = performance_collector._define_epochs_to_process_range(finalized_epoch)

        # Should start from next epoch after max_epoch_in_db
        assert result == (EpochNumber(91), EpochNumber(98))

    @pytest.mark.unit
    def test_unsatisfied_epochs_demand_affects_start_epoch(
        self, performance_collector: PerformanceCollector, mock_db: Mock
    ):
        """Test when there's unsatisfied demand - should affect start epoch"""
        finalized_epoch = EpochNumber(100)

        # Setup DB
        mock_db.min_epoch.return_value = 50
        mock_db.max_epoch.return_value = 90
        mock_db.get_epochs_demands.return_value = [
            EpochsDemand(consumer='consumer1', from_epoch=20, to_epoch=30, updated_at=UPDATED_AT)
        ]
        mock_db.is_range_available.return_value = False  # Unsatisfied demand
        # When missing_epochs_in is called with (20, 98), return missing epochs in that range
        mock_db.missing_epochs_in.return_value = list(range(20, 50)) + list(range(91, 99))

        result = performance_collector._define_epochs_to_process_range(finalized_epoch)

        # start_epoch should be min(98, 20) = 20 due to unsatisfied demand, then min of missing epochs
        assert result == (EpochNumber(20), EpochNumber(98))

    @pytest.mark.unit
    def test_satisfied_epochs_demand_ignored(self, performance_collector: PerformanceCollector, mock_db: Mock):
        """Test that satisfied epochs demand is ignored"""
        finalized_epoch = EpochNumber(100)

        # Setup DB
        mock_db.min_epoch.return_value = 50
        mock_db.max_epoch.return_value = 90
        mock_db.get_epochs_demands.return_value = [
            EpochsDemand(consumer='consumer1', from_epoch=60, to_epoch=70, updated_at=UPDATED_AT)
        ]
        mock_db.is_range_available.return_value = True  # Satisfied demand
        mock_db.missing_epochs_in.return_value = []

        result = performance_collector._define_epochs_to_process_range(finalized_epoch)

        # Satisfied demand should be deleted from the DB
        mock_db.delete_demand.assert_called_once()
        # Should start from next epoch after max (ignoring satisfied demand)
        assert result == (EpochNumber(91), EpochNumber(98))

    @pytest.mark.unit
    def test_multiple_demands_with_mixed_satisfaction(self, performance_collector: PerformanceCollector, mock_db: Mock):
        """Test with multiple demands - some satisfied, some not"""
        finalized_epoch = EpochNumber(200)

        # Setup DB
        mock_db.min_epoch.return_value = 50
        mock_db.max_epoch.return_value = 90
        mock_db.get_epochs_demands.return_value = [
            EpochsDemand(consumer='consumer1', from_epoch=20, to_epoch=30, updated_at=UPDATED_AT),  # Unsatisfied
            EpochsDemand(consumer='consumer2', from_epoch=95, to_epoch=105, updated_at=UPDATED_AT),  # Unsatisfied
            EpochsDemand(consumer='consumer3', from_epoch=60, to_epoch=70, updated_at=UPDATED_AT),  # Satisfied
        ]

        def mock_is_range_available(from_epoch, to_epoch):
            return from_epoch == 60 and to_epoch == 70

        mock_db.is_range_available.side_effect = mock_is_range_available
        # After processing demands, start_epoch becomes min(198, 20, 95) = 20
        mock_db.missing_epochs_in.return_value = list(range(20, 50)) + list(range(91, 199))

        result = performance_collector._define_epochs_to_process_range(finalized_epoch)

        # start_epoch should be min(198, 20, 95) = 20 from unsatisfied demands
        assert result == (EpochNumber(20), EpochNumber(198))

    @pytest.mark.unit
    def test_gap_in_empty_db_handling(self, performance_collector: PerformanceCollector, mock_db: Mock):
        """Test handling when DB is empty but missing_epochs_in is called"""
        finalized_epoch = EpochNumber(100)

        # Setup empty DB
        mock_db.min_epoch.return_value = None
        mock_db.max_epoch.return_value = None
        mock_db.get_epochs_demands.return_value = []
        mock_db.missing_epochs_in.return_value = [EpochNumber(98)]

        assert performance_collector._define_epochs_to_process_range(finalized_epoch) == (
            EpochNumber(98),
            EpochNumber(98),
        )

    @pytest.mark.unit
    def test_start_epoch_exceeds_max_available(self, performance_collector: PerformanceCollector, mock_db: Mock):
        """Test when start_epoch > max_available_epoch_to_check"""
        finalized_epoch = EpochNumber(100)

        # Setup DB
        mock_db.min_epoch.return_value = 50
        mock_db.max_epoch.return_value = 98  # High max_epoch
        mock_db.get_epochs_demands.return_value = [
            EpochsDemand(consumer='consumer1', from_epoch=50, to_epoch=99, updated_at=UPDATED_AT)
        ]
        mock_db.is_range_available.return_value = False
        mock_db.missing_epochs_in.return_value = []  # No gaps

        result = performance_collector._define_epochs_to_process_range(finalized_epoch)

        # max_epoch_in_db is 98, so start_epoch becomes 99; since max_available is 98, it should return None
        assert result is None

    @pytest.mark.unit
    def test_cl_node_not_synced_error(self, performance_collector: PerformanceCollector, mock_db: Mock):
        """Test raising when max_epoch_in_db exceeds max_available_epoch_to_check."""
        finalized_epoch = EpochNumber(100)

        # Setup DB where max_epoch_in_db (99) > max_available_epoch_to_check (98)
        mock_db.min_epoch.return_value = 50
        mock_db.max_epoch.return_value = 99
        mock_db.get_epochs_demands.return_value = []
        mock_db.missing_epochs_in.return_value = []

        with pytest.raises(ValueError, match="CL node is not synced"):
            performance_collector._define_epochs_to_process_range(finalized_epoch)

    @pytest.mark.unit
    def test_complex_scenario_with_gaps_and_demands(self, performance_collector: PerformanceCollector, mock_db: Mock):
        """Test complex scenario with gaps and demands"""
        finalized_epoch = EpochNumber(200)

        # Setup DB with some data
        mock_db.min_epoch.return_value = 30
        mock_db.max_epoch.return_value = 150
        mock_db.get_epochs_demands.return_value = [
            EpochsDemand(consumer='consumer1', from_epoch=10, to_epoch=25, updated_at=UPDATED_AT),
        ]
        mock_db.is_range_available.return_value = False  # Unsatisfied demand
        # After processing demand: start_epoch becomes min(198, 10) = 10
        mock_db.missing_epochs_in.return_value = list(range(10, 30)) + [100, 101, 102] + list(range(151, 199))

        result = performance_collector._define_epochs_to_process_range(finalized_epoch)

        # start_epoch should be min from missing epochs = 10
        assert result == (EpochNumber(10), EpochNumber(198))

    @pytest.mark.unit
    def test_no_epochs_demand_logging(
        self, performance_collector: PerformanceCollector, mock_db: Mock, caplog: pytest.LogCaptureFixture
    ):
        """Test that 'No epoch demands found' is logged when appropriate"""
        finalized_epoch = EpochNumber(100)

        # Setup DB
        mock_db.min_epoch.return_value = 50
        mock_db.max_epoch.return_value = 90
        mock_db.get_epochs_demands.return_value = []  # No demands
        mock_db.missing_epochs_in.return_value = []

        with caplog.at_level('INFO'):
            result = performance_collector._define_epochs_to_process_range(finalized_epoch)

        assert "No epoch demands found" in caplog.text
        assert result == (EpochNumber(91), EpochNumber(98))


class TestExecuteModule:
    @pytest.fixture
    def converter(self) -> Mock:
        return Mock(get_epoch_by_slot=Mock(return_value=100))

    @pytest.fixture(autouse=True)
    def setup_collector(self, performance_collector: PerformanceCollector, converter: Mock) -> None:
        """Mock internal methods common to all execute_module tests"""
        performance_collector._build_converter = Mock(return_value=converter)
        performance_collector._update_demand_metrics = Mock()
        performance_collector._reset_cycle_timeout = Mock()

    @pytest.mark.unit
    def test_returns_next_finalized_epoch_when_no_epochs_to_process(
        self, performance_collector: PerformanceCollector, converter: Mock
    ):
        converter.get_epoch_by_slot.return_value = 10
        performance_collector._define_epochs_to_process_range = Mock(return_value=None)

        result = performance_collector.execute_module(Mock())

        assert result is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH
        cast(Mock, performance_collector._update_demand_metrics).assert_called_once_with()
        cast(Mock, performance_collector._define_epochs_to_process_range).assert_called_once_with(EpochNumber(9))

    @pytest.mark.unit
    def test_processes_all_checkpoints_when_no_new_demand(
        self, performance_collector: PerformanceCollector, converter: Mock
    ):
        blockstamp = Mock()
        start_epoch, end_epoch = EpochNumber(90), EpochNumber(98)
        checkpoints = [Mock(slot=10), Mock(slot=20)]

        performance_collector._define_epochs_to_process_range = Mock(return_value=(start_epoch, end_epoch))
        performance_collector._has_epochs_demand_changed = Mock(return_value=False)

        processor = Mock(exec=Mock(side_effect=[[EpochNumber(90)], [EpochNumber(91)]]))

        with (
            patch.object(collector_module, 'FrameCheckpointsIterator', return_value=checkpoints) as iterator_mock,
            patch.object(collector_module, 'FrameCheckpointProcessor', return_value=processor) as processor_mock,
        ):
            result = performance_collector.execute_module(blockstamp)

        assert result is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH
        iterator_mock.assert_called_once_with(converter, start_epoch, end_epoch, EpochNumber(99))
        processor_mock.assert_called_once_with(
            performance_collector.cc,
            performance_collector.db,
            converter,
            blockstamp,
        )
        assert processor.exec.call_count == len(checkpoints)
        assert cast(Mock, performance_collector._reset_cycle_timeout).call_count == len(checkpoints)
        assert cast(Mock, performance_collector._has_epochs_demand_changed).call_count == len(checkpoints)

    @pytest.mark.unit
    def test_empty_checkpoints_returns_next_finalized_epoch(self, performance_collector: PerformanceCollector):
        """Test when FrameCheckpointsIterator yields no checkpoints"""
        performance_collector._define_epochs_to_process_range = Mock(return_value=(..., ...))
        performance_collector._has_epochs_demand_changed = Mock()

        processor = Mock()

        with (
            patch.object(collector_module, 'FrameCheckpointsIterator', return_value=[]),
            patch.object(collector_module, 'FrameCheckpointProcessor', return_value=processor),
        ):
            result = performance_collector.execute_module(Mock())

        assert result is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH
        processor.exec.assert_not_called()
        cast(Mock, performance_collector._reset_cycle_timeout).assert_not_called()
        cast(Mock, performance_collector._has_epochs_demand_changed).assert_not_called()

    @pytest.mark.unit
    def test_stops_on_new_demand(self, performance_collector: PerformanceCollector):
        """Test that processing stops mid-sequence when new demand appears"""
        checkpoints = [Mock(slot=10), Mock(slot=20), Mock(slot=30)]

        performance_collector._define_epochs_to_process_range = Mock(return_value=(..., ...))
        performance_collector._has_epochs_demand_changed = Mock(side_effect=[False, True])

        processor = Mock()
        processor.exec.side_effect = [[...], [...]]

        with (
            patch.object(collector_module, 'FrameCheckpointsIterator', return_value=checkpoints),
            patch.object(collector_module, 'FrameCheckpointProcessor', return_value=processor),
        ):
            result = performance_collector.execute_module(Mock())

        assert result is ModuleExecuteDelay.NEXT_SLOT
        assert processor.exec.call_count == 2
        processor.exec.assert_has_calls([call(checkpoints[0]), call(checkpoints[1])])
        assert cast(Mock, performance_collector._reset_cycle_timeout).call_count == 2
        assert cast(Mock, performance_collector._has_epochs_demand_changed).call_count == 2

    @pytest.mark.unit
    def test_checkpoints_processed_in_order(self, performance_collector: PerformanceCollector):
        """Test that each checkpoint is passed to processor.exec in iteration order"""
        checkpoints = [Mock(slot=10), Mock(slot=20), Mock(slot=30)]

        performance_collector._define_epochs_to_process_range = Mock(return_value=(EpochNumber(90), EpochNumber(98)))
        performance_collector._has_epochs_demand_changed = Mock(return_value=False)

        processor = Mock()
        processor.exec.side_effect = [[EpochNumber(90)], [EpochNumber(91)], [EpochNumber(92)]]

        with (
            patch.object(collector_module, 'FrameCheckpointsIterator', return_value=checkpoints),
            patch.object(collector_module, 'FrameCheckpointProcessor', return_value=processor),
        ):
            performance_collector.execute_module(Mock())

        # Verify exact call order
        assert processor.exec.call_count == len(checkpoints)
        expected_call_seq = [call(ch) for ch in checkpoints]
        processor.exec.assert_has_calls(expected_call_seq, any_order=False)


class TestHasEpochsDemandChanged:
    @pytest.mark.unit
    def test_no_change(self, performance_collector: PerformanceCollector, mock_db: Mock):
        performance_collector.last_epochs_demand_update = T0
        performance_collector.last_demands_count = 0
        mock_db.get_epochs_demands_max_updated_at.return_value = T0
        mock_db.demands_count.return_value = 0

        assert performance_collector._has_epochs_demand_changed() is False

    @pytest.mark.unit
    def test_detects_new_demand_by_updated_at(self, performance_collector: PerformanceCollector, mock_db: Mock):
        performance_collector.last_epochs_demand_update = T0
        performance_collector.last_demands_count = 1
        mock_db.get_epochs_demands_max_updated_at.return_value = T1
        mock_db.demands_count.return_value = 1

        assert performance_collector._has_epochs_demand_changed() is True
        assert performance_collector.last_epochs_demand_update == T1

    @pytest.mark.unit
    def test_detects_demand_deletion_by_count(self, performance_collector: PerformanceCollector, mock_db: Mock):
        performance_collector.last_epochs_demand_update = T0
        performance_collector.last_demands_count = 2
        mock_db.get_epochs_demands_max_updated_at.return_value = T0
        mock_db.demands_count.return_value = 1

        assert performance_collector._has_epochs_demand_changed() is True
        assert performance_collector.last_demands_count == 1

    @pytest.mark.unit
    def test_detects_all_demands_deleted(self, performance_collector: PerformanceCollector, mock_db: Mock):
        performance_collector.last_epochs_demand_update = T0
        performance_collector.last_demands_count = 1
        mock_db.get_epochs_demands_max_updated_at.return_value = None
        mock_db.demands_count.return_value = 0

        assert performance_collector._has_epochs_demand_changed() is True
        assert performance_collector.last_demands_count == 0
        assert performance_collector.last_epochs_demand_update is None

    @pytest.mark.unit
    def test_no_change_on_empty_table(self, performance_collector: PerformanceCollector, mock_db: Mock):
        performance_collector.last_epochs_demand_update = None
        performance_collector.last_demands_count = 0
        mock_db.get_epochs_demands_max_updated_at.return_value = None
        mock_db.demands_count.return_value = 0

        assert performance_collector._has_epochs_demand_changed() is False
