from unittest.mock import Mock, patch

import pytest

import src.modules.sidecars.performance.collector.collector as collector_module
from src.modules.sidecars.performance.collector.checkpoint import FrameCheckpointsIterator
from src.modules.sidecars.performance.collector.collector import PerformanceCollector
from src.modules.sidecars.performance.common.db import DutiesDB, EpochsDemand
from src.types import EpochNumber


UPDATED_AT = None


@pytest.fixture
def mock_w3():
    """Mock Web3 instance"""
    return Mock()


@pytest.fixture
def mock_db():
    """Mock DutiesDB instance"""
    return Mock(spec=DutiesDB)


@pytest.fixture
def performance_collector(mock_w3, mock_db):
    """Create PerformanceCollector instance with mocked dependencies"""
    with patch.object(collector_module, 'DutiesDB', return_value=mock_db):
        mock_db.get_epochs_demands_max_updated_at.return_value = 0
        collector = PerformanceCollector(mock_w3)
        return collector


class TestDefineEpochsToProcessRange:
    """Test cases for define_epochs_to_process_range method"""

    @pytest.mark.unit
    def test_empty_db_default_range(self, performance_collector, mock_db):
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
    def test_finalized_epoch_less_than_checkpoint_delay_returns_none(self, performance_collector, mock_db):
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
    def test_db_with_gap_and_no_current_demands_process_missing_epochs(self, performance_collector, mock_db):
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
        assert result[0] == EpochNumber(50)
        assert result[1] == EpochNumber(98)

    @pytest.mark.unit
    def test_db_min_epoch_zero_is_used_as_start(self, performance_collector, mock_db):
        finalized_epoch = EpochNumber(100)

        mock_db.min_epoch.return_value = 0
        mock_db.max_epoch.return_value = 90
        mock_db.get_epochs_demands.return_value = []
        mock_db.missing_epochs_in.return_value = [0, 1, 2]

        result = performance_collector._define_epochs_to_process_range(finalized_epoch)

        mock_db.missing_epochs_in.assert_called_once_with(0, 98)
        assert result[0] == EpochNumber(0)
        assert result[1] == EpochNumber(98)

    @pytest.mark.unit
    def test_db_with_gap_process_missing_epochs(self, performance_collector, mock_db):
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
        assert result[0] == EpochNumber(50)
        assert result[1] == EpochNumber(98)

    @pytest.mark.unit
    def test_db_without_gap_continues_from_last(self, performance_collector, mock_db):
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
        assert result[0] == EpochNumber(91)
        assert result[1] == EpochNumber(98)

    @pytest.mark.unit
    def test_unsatisfied_epochs_demand_affects_start_epoch(self, performance_collector, mock_db):
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
        assert result[0] == EpochNumber(20)
        assert result[1] == EpochNumber(98)

    @pytest.mark.unit
    def test_satisfied_epochs_demand_ignored(self, performance_collector, mock_db):
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

        # Should start from next epoch after max (ignoring satisfied demand)
        assert result[0] == EpochNumber(91)
        assert result[1] == EpochNumber(98)

    @pytest.mark.unit
    def test_multiple_demands_with_mixed_satisfaction(self, performance_collector, mock_db):
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
        assert result[0] == EpochNumber(20)
        assert result[1] == EpochNumber(198)

    @pytest.mark.unit
    def test_gap_in_empty_db_handling(self, performance_collector, mock_db):
        """Test handling when DB is empty but missing_epochs_in is called"""
        finalized_epoch = EpochNumber(100)

        # Setup empty DB
        mock_db.min_epoch.return_value = None
        mock_db.max_epoch.return_value = None
        mock_db.get_epochs_demands.return_value = []
        mock_db.missing_epochs_in.return_value = []

        # This should raise ValueError as per the logic
        with pytest.raises(ValueError, match="No missing epochs found but the DB is empty"):
            performance_collector._define_epochs_to_process_range(finalized_epoch)

    @pytest.mark.unit
    def test_start_epoch_exceeds_max_available(self, performance_collector, mock_db):
        """Test when start_epoch > max_available_epoch_to_check"""
        finalized_epoch = EpochNumber(100)

        # Setup DB
        mock_db.min_epoch.return_value = 50
        mock_db.max_epoch.return_value = 99  # High max_epoch
        mock_db.get_epochs_demands.return_value = []
        mock_db.missing_epochs_in.return_value = []  # No gaps

        result = performance_collector._define_epochs_to_process_range(finalized_epoch)

        # start_epoch would be 100, but max_available is 98, so should return None
        assert result is None

    @pytest.mark.unit
    def test_cl_node_not_synced_error(self, performance_collector, mock_db):
        """Test when CL node is not synced (max_available < min_epoch_in_db)"""
        finalized_epoch = EpochNumber(5)

        # Setup DB where min_epoch is higher than what we can process
        mock_db.min_epoch.return_value = 10  # min_epoch > max_available(3)
        mock_db.max_epoch.return_value = 100

        with pytest.raises(ValueError, match="CL node is not synced"):
            performance_collector._define_epochs_to_process_range(finalized_epoch)

    @pytest.mark.unit
    def test_complex_scenario_with_gaps_and_demands(self, performance_collector, mock_db):
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
        assert result[0] == EpochNumber(10)  # From demand and missing epochs
        assert result[1] == EpochNumber(198)

    @pytest.mark.unit
    def test_no_epochs_demand_logging(self, performance_collector, mock_db, caplog):
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
        assert result[0] == EpochNumber(91)
        assert result[1] == EpochNumber(98)
