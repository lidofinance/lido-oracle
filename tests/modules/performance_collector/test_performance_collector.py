import pytest
from unittest.mock import Mock, patch

from src.modules.performance_collector.performance_collector import PerformanceCollector
from src.modules.performance_collector.db import DutiesDB
from src.types import EpochNumber


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
    from pathlib import Path
    mock_cache_path = Path('/tmp')

    with patch('src.modules.performance_collector.performance_collector.DutiesDB', return_value=mock_db), \
         patch('src.modules.performance_collector.performance_collector.start_performance_api_server'), \
         patch('src.modules.performance_collector.performance_collector.variables.CACHE_PATH', mock_cache_path), \
         patch('src.modules.performance_collector.performance_collector.variables.PERFORMANCE_COLLECTOR_SERVER_API_PORT', 8080):
        collector = PerformanceCollector(mock_w3)
        collector.db = mock_db
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
        mock_db.epochs_demand.return_value = {}

        result = performance_collector.define_epochs_to_process_range(finalized_epoch)

        # Expected calculations:
        # max_available_epoch_to_check = max(0, 100 - 2) = 98
        # start_epoch = 98
        # end_epoch = 98
        assert result == (EpochNumber(98), EpochNumber(98))

    @pytest.mark.unit
    def test_empty_db_with_low_finalized_epoch(self, performance_collector, mock_db):
        """Test when finalized epoch is low and DB is empty"""
        finalized_epoch = EpochNumber(5)

        # Setup empty DB
        mock_db.min_epoch.return_value = None
        mock_db.max_epoch.return_value = None
        mock_db.epochs_demand.return_value = {}

        result = performance_collector.define_epochs_to_process_range(finalized_epoch)

        # Expected calculations:
        # max_available_epoch_to_check = max(0, 5 - 2) = 3
        # start_epoch = 3
        # end_epoch = 3
        assert result == (EpochNumber(3), EpochNumber(3))

    @pytest.mark.unit
    def test_db_with_gap_in_range(self, performance_collector, mock_db):
        """Test when there's a gap in the database"""
        finalized_epoch = EpochNumber(100)

        # Setup DB with gap
        mock_db.min_epoch.return_value = 10
        mock_db.max_epoch.return_value = 90
        mock_db.missing_epochs_in.return_value = [50, 51, 52]  # Gap in the middle
        mock_db.epochs_demand.return_value = {}

        result = performance_collector.define_epochs_to_process_range(finalized_epoch)

        # Should start from the first missing epoch
        assert result[0] == EpochNumber(50)
        # End epoch should be max_available = max(0, 100 - 2) = 98
        assert result[1] == EpochNumber(98)

    @pytest.mark.unit
    def test_db_without_gap_continuous_collection(self, performance_collector, mock_db):
        """Test when DB has no gaps - should collect next epochs"""
        finalized_epoch = EpochNumber(100)

        # Setup DB without gaps
        mock_db.min_epoch.return_value = 10
        mock_db.max_epoch.return_value = 90
        mock_db.missing_epochs_in.return_value = []  # No gaps
        mock_db.epochs_demand.return_value = {}

        result = performance_collector.define_epochs_to_process_range(finalized_epoch)

        # Should start from next epoch after max
        # start_epoch = 90 + 1 = 91
        assert result[0] == EpochNumber(91)
        # End epoch should be max_available = max(0, 100 - 2) = 98
        assert result[1] == EpochNumber(98)

    @pytest.mark.unit
    def test_unsatisfied_epochs_demand_before_db_range(self, performance_collector, mock_db):
        """Test when there's unsatisfied demand before existing DB range"""
        finalized_epoch = EpochNumber(100)

        # Setup DB
        mock_db.min_epoch.return_value = 50
        mock_db.max_epoch.return_value = 90
        mock_db.missing_epochs_in.return_value = []

        # Setup epochs demand before DB range
        mock_db.epochs_demand.return_value = {
            'consumer1': (20, 30)  # Demand before min_epoch_in_db
        }
        mock_db.is_range_available.return_value = False  # Unsatisfied demand

        result = performance_collector.define_epochs_to_process_range(finalized_epoch)

        # Should start from the earliest demand
        assert result[0] == EpochNumber(20)
        # End epoch should be max_available = max(0, 100 - 2) = 98
        assert result[1] == EpochNumber(98)

    @pytest.mark.unit
    def test_unsatisfied_epochs_demand_after_db_range(self, performance_collector, mock_db):
        """Test when there's unsatisfied demand after existing DB range"""
        finalized_epoch = EpochNumber(200)

        # Setup DB
        mock_db.min_epoch.return_value = 50
        mock_db.max_epoch.return_value = 90
        mock_db.missing_epochs_in.return_value = []

        # Setup epochs demand after DB range
        mock_db.epochs_demand.return_value = {
            'consumer1': (95, 105)  # Demand after max_epoch_in_db
        }
        mock_db.is_range_available.return_value = False  # Unsatisfied demand

        result = performance_collector.define_epochs_to_process_range(finalized_epoch)

        # Should start from next epoch after max DB epoch
        assert result[0] == EpochNumber(91)
        assert result[1] == EpochNumber(198)

    @pytest.mark.unit
    def test_satisfied_epochs_demand_ignored(self, performance_collector, mock_db):
        """Test that satisfied epochs demand is ignored"""
        finalized_epoch = EpochNumber(100)

        # Setup DB
        mock_db.min_epoch.return_value = 50
        mock_db.max_epoch.return_value = 90
        mock_db.missing_epochs_in.return_value = []

        # Setup satisfied epochs demand
        mock_db.epochs_demand.return_value = {
            'consumer1': (60, 70)  # Demand within DB range
        }
        mock_db.is_range_available.return_value = True  # Satisfied demand

        result = performance_collector.define_epochs_to_process_range(finalized_epoch)

        # Should start from next epoch after max (ignoring satisfied demand)
        assert result[0] == EpochNumber(91)
        # End epoch should be max_available = max(0, 100 - 2) = 98
        assert result[1] == EpochNumber(98)

    @pytest.mark.unit
    def test_multiple_unsatisfied_demands(self, performance_collector, mock_db):
        """Test with multiple unsatisfied demands"""
        finalized_epoch = EpochNumber(200)

        # Setup DB
        mock_db.min_epoch.return_value = 50
        mock_db.max_epoch.return_value = 90
        mock_db.missing_epochs_in.return_value = []

        # Setup multiple unsatisfied demands
        mock_db.epochs_demand.return_value = {
            'consumer1': (20, 30),   # Before DB range
            'consumer2': (95, 105),  # After DB range
            'consumer3': (60, 70),   # Within DB range (satisfied)
        }

        def mock_is_range_available(l_epoch, r_epoch):
            if l_epoch == 60 and r_epoch == 70:
                return True  # Satisfied
            return False  # Unsatisfied

        mock_db.is_range_available.side_effect = mock_is_range_available

        result = performance_collector.define_epochs_to_process_range(finalized_epoch)

        # Should take the minimum of unsatisfied demands for start
        # start_epoch = min(91, 20) = 20  (91 from DB continuation, 20 from demand)
        assert result[0] == EpochNumber(20)
        assert result[1] == EpochNumber(198)

    @pytest.mark.unit
    def test_very_low_finalized_epoch(self, performance_collector, mock_db):
        """Test with very low finalized epoch (edge case)"""
        finalized_epoch = EpochNumber(1)

        # Setup empty DB
        mock_db.min_epoch.return_value = None
        mock_db.max_epoch.return_value = None
        mock_db.epochs_demand.return_value = {}

        result = performance_collector.define_epochs_to_process_range(finalized_epoch)

        # max_available_epoch_to_check = (1 - 2) = -1
        assert result is None

    @pytest.mark.unit
    def test_no_epochs_demand_logged(self, performance_collector, mock_db, caplog):
        """Test logging when no epochs demand is found"""
        finalized_epoch = EpochNumber(100)

        # Setup DB
        mock_db.min_epoch.return_value = 50
        mock_db.max_epoch.return_value = 90
        mock_db.missing_epochs_in.return_value = []
        mock_db.epochs_demand.return_value = {}  # No demand

        with caplog.at_level('INFO'):
            result = performance_collector.define_epochs_to_process_range(finalized_epoch)

        assert "No epochs demand found" in caplog.text
        assert result is not None

    @pytest.mark.unit
    def test_complex_scenario_with_gap_and_demand(self, performance_collector, mock_db):
        """Test complex scenario with both gaps and unsatisfied demand"""
        finalized_epoch = EpochNumber(200)

        # Setup DB with gap
        mock_db.min_epoch.return_value = 30
        mock_db.max_epoch.return_value = 150
        mock_db.missing_epochs_in.return_value = [100, 101, 102]  # Gap in DB

        # Setup unsatisfied demand
        mock_db.epochs_demand.return_value = {
            'consumer1': (10, 20),   # Before DB range
        }
        mock_db.is_range_available.return_value = False  # Unsatisfied

        result = performance_collector.define_epochs_to_process_range(finalized_epoch)

        # Should start from gap (100) vs demand (10) -> min(100, 10) = 10
        assert result[0] == EpochNumber(10)
        # End epoch should be max_available = max(0, 200 - 2) = 198
        assert result[1] == EpochNumber(198)

    @pytest.mark.unit
    def test_finalized_epoch_zero(self, performance_collector, mock_db):
        """Test with zero finalized epoch (edge case)"""
        finalized_epoch = EpochNumber(0)

        # Setup empty DB
        mock_db.min_epoch.return_value = None
        mock_db.max_epoch.return_value = None
        mock_db.epochs_demand.return_value = {}

        result = performance_collector.define_epochs_to_process_range(finalized_epoch)

        # max_available_epoch_to_check = -2
        assert result is None

    @pytest.mark.unit
    def test_epochs_demand_exactly_at_db_boundaries(self, performance_collector, mock_db):
        """Test epochs demand exactly at database boundaries"""
        finalized_epoch = EpochNumber(200)

        # Setup DB
        mock_db.min_epoch.return_value = 50
        mock_db.max_epoch.return_value = 90
        mock_db.missing_epochs_in.return_value = []

        # Setup demand exactly at boundaries
        mock_db.epochs_demand.return_value = {
            'consumer1': (50, 90),  # Exactly the DB range
        }
        mock_db.is_range_available.return_value = True  # Satisfied demand

        result = performance_collector.define_epochs_to_process_range(finalized_epoch)

        # Should ignore satisfied demand and continue from max + 1
        assert result[0] == EpochNumber(91)
        # End epoch should be max_available = max(0, 200 - 2) = 198
        assert result[1] == EpochNumber(198)

    @pytest.mark.unit
    def test_negative_start_epoch_calculation(self, performance_collector, mock_db):
        """Test when calculation would result in negative start epoch"""
        finalized_epoch = EpochNumber(5)  # Very low

        # Setup DB that would lead to high start epoch
        mock_db.min_epoch.return_value = 100
        mock_db.max_epoch.return_value = 200
        mock_db.missing_epochs_in.return_value = []
        mock_db.epochs_demand.return_value = {}

        with pytest.raises(ValueError):
            # Finalized epoch is lower than min_epoch_in_db
            performance_collector.define_epochs_to_process_range(finalized_epoch)

    @pytest.mark.unit
    def test_overlapping_epochs_demands(self, performance_collector, mock_db):
        """Test with overlapping epochs demands"""
        finalized_epoch = EpochNumber(200)

        # Setup DB
        mock_db.min_epoch.return_value = 80
        mock_db.max_epoch.return_value = 120
        mock_db.missing_epochs_in.return_value = []

        # Setup overlapping demands
        mock_db.epochs_demand.return_value = {
            'consumer1': (40, 60),   # Before DB range
            'consumer2': (50, 70),   # Overlapping with consumer1
            'consumer3': (140, 160), # After DB range
        }
        mock_db.is_range_available.return_value = False  # All unsatisfied

        result = performance_collector.define_epochs_to_process_range(finalized_epoch)

        # Should take the earliest start (40) and appropriate end
        assert result[0] == EpochNumber(40)
        assert result[1] == EpochNumber(198)

    @pytest.mark.unit
    def test_empty_epochs_demand_dict(self, performance_collector, mock_db):
        """Test with explicitly empty epochs demand dictionary"""
        finalized_epoch = EpochNumber(100)

        # Setup DB
        mock_db.min_epoch.return_value = 50
        mock_db.max_epoch.return_value = 90
        mock_db.missing_epochs_in.return_value = []
        mock_db.epochs_demand.return_value = {}  # Explicitly empty

        result = performance_collector.define_epochs_to_process_range(finalized_epoch)

        # Should proceed with normal DB continuation logic
        assert result[0] == EpochNumber(91)
        assert result[1] == EpochNumber(98)  # max_available = 98

    @pytest.mark.unit
    def test_gap_at_beginning_of_db_range(self, performance_collector, mock_db):
        """Test when gap is at the very beginning of DB range"""
        finalized_epoch = EpochNumber(100)

        # Setup DB with gap at the beginning
        mock_db.min_epoch.return_value = 10
        mock_db.max_epoch.return_value = 90
        mock_db.missing_epochs_in.return_value = [10, 11, 12]  # Gap at beginning
        mock_db.epochs_demand.return_value = {}

        result = performance_collector.define_epochs_to_process_range(finalized_epoch)

        # Should start from the first missing epoch
        assert result[0] == EpochNumber(10)
        # End epoch should be max_available = max(0, 100 - 2) = 98
        assert result[1] == EpochNumber(98)

    @pytest.mark.unit
    def test_gap_at_end_of_db_range(self, performance_collector, mock_db):
        """Test when gap is at the very end of DB range"""
        finalized_epoch = EpochNumber(100)

        # Setup DB with gap at the end
        mock_db.min_epoch.return_value = 10
        mock_db.max_epoch.return_value = 90
        mock_db.missing_epochs_in.return_value = [88, 89, 90]  # Gap at end
        mock_db.epochs_demand.return_value = {}

        result = performance_collector.define_epochs_to_process_range(finalized_epoch)

        # Should start from the first missing epoch
        assert result[0] == EpochNumber(88)
        # End epoch should be max_available = max(0, 100 - 2) = 98
        assert result[1] == EpochNumber(98)

