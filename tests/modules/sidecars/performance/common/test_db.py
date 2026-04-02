from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from src import variables
from src.modules.sidecars.performance.common.db import (
    RETENTION_EPOCHS_DEFAULT,
    DutiesDB,
    Duty,
    EpochsDemand,
    IncompleteEpochRangeError,
    Settings,
)
from src.modules.sidecars.performance.common.types import ProposalDuty, SyncDuty
from src.types import EpochNumber


pytestmark = pytest.mark.unit


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    return session


@pytest.fixture
def db(mock_session):
    with (
        patch('src.modules.sidecars.performance.common.db.create_engine'),
        patch('src.modules.sidecars.performance.common.db.SQLModel'),
    ):
        instance = DutiesDB()
    instance.get_session = Mock(return_value=mock_session)
    return instance


class TestBuildEngine:
    def test_build_engine_with_connect_timeout(self):
        with (
            patch('src.modules.sidecars.performance.common.db.create_engine') as mock_create_engine,
            patch('src.modules.sidecars.performance.common.db.SQLModel'),
        ):
            DutiesDB(connect_timeout=5)
            _, kwargs = mock_create_engine.call_args
            assert kwargs['connect_args']['connect_timeout'] == 5

    def test_build_engine_with_statement_timeout(self):
        with (
            patch('src.modules.sidecars.performance.common.db.create_engine') as mock_create_engine,
            patch('src.modules.sidecars.performance.common.db.SQLModel'),
        ):
            DutiesDB(statement_timeout_ms=1000)
            _, kwargs = mock_create_engine.call_args
            assert kwargs['connect_args']['options'] == '-c statement_timeout=1000'

    def test_build_engine_without_optional_args(self):
        with (
            patch('src.modules.sidecars.performance.common.db.create_engine') as mock_create_engine,
            patch('src.modules.sidecars.performance.common.db.SQLModel'),
        ):
            DutiesDB()
            _, kwargs = mock_create_engine.call_args
            assert kwargs['connect_args'] == {}

    def test_get_database_url_uses_db_variables(self, monkeypatch):
        monkeypatch.setattr(variables, 'PERFORMANCE_DB_USER', 'test_user')
        monkeypatch.setattr(variables, 'PERFORMANCE_DB_PASSWORD', 'test_pass')
        monkeypatch.setattr(variables, 'PERFORMANCE_DB_HOST', 'db.example.com')
        monkeypatch.setattr(variables, 'PERFORMANCE_DB_PORT', 5433)
        monkeypatch.setattr(variables, 'PERFORMANCE_DB_NAME', 'test_db')

        assert DutiesDB._get_database_url() == 'postgresql://test_user:test_pass@db.example.com:5433/test_db'


class TestStoreDemand:
    def test_store_demand_creates_new(self, db, mock_session):
        mock_session.get.return_value = None

        result = db.store_demand('consumer-1', EpochNumber(10), EpochNumber(20))

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        added_demand = mock_session.add.call_args[0][0]
        assert added_demand.consumer == 'consumer-1'
        assert added_demand.from_epoch == 10
        assert added_demand.to_epoch == 20
        assert result is added_demand

    def test_store_demand_updates_existing(self, db, mock_session):
        old_time = datetime(2024, 1, 1, tzinfo=UTC)
        existing = EpochsDemand(consumer='consumer-1', from_epoch=5, to_epoch=15, updated_at=old_time)
        mock_session.get.return_value = existing

        result = db.store_demand('consumer-1', EpochNumber(10), EpochNumber(25))

        mock_session.add.assert_not_called()
        mock_session.commit.assert_called_once()
        assert result.from_epoch == 10
        assert result.to_epoch == 25
        assert result.updated_at > old_time


class TestDeleteDemand:
    def test_delete_demand(self, db, mock_session):
        demand = EpochsDemand(consumer='consumer-1', from_epoch=1, to_epoch=10)
        db.delete_demand(demand)

        mock_session.delete.assert_called_once_with(demand)
        mock_session.commit.assert_called_once()


class TestSettings:
    def test_get_retention_epochs_returns_value(self, db, mock_session):
        from src.modules.sidecars.performance.common.db import Settings

        mock_session.get.return_value = Settings(key='retention_epochs', value=500)

        result = db.get_retention_epochs()

        assert result == 500
        mock_session.get.assert_called_once_with(Settings, 'retention_epochs')

    def test_get_retention_epochs_raises_when_missing(self, db, mock_session):
        mock_session.get.return_value = None

        with pytest.raises(ValueError, match="'retention_epochs' setting not found"):
            db.get_retention_epochs()

    def test_get_retention_epochs_raises_on_non_int_value(self, db, mock_session):
        from src.modules.sidecars.performance.common.db import Settings

        mock_session.get.return_value = Settings(key='retention_epochs', value='not an int')

        with pytest.raises(TypeError, match="expected an int, got str"):
            db.get_retention_epochs()

    def test_get_retention_epochs_raises_on_zero(self, db, mock_session):
        from src.modules.sidecars.performance.common.db import Settings

        mock_session.get.return_value = Settings(key='retention_epochs', value=0)

        with pytest.raises(ValueError, match="must be positive, got 0"):
            db.get_retention_epochs()

    def test_get_retention_epochs_raises_on_negative(self, db, mock_session):
        from src.modules.sidecars.performance.common.db import Settings

        mock_session.get.return_value = Settings(key='retention_epochs', value=-5)

        with pytest.raises(ValueError, match="must be positive, got -5"):
            db.get_retention_epochs()

    def test_set_retention_epochs_updates_existing(self, db, mock_session):
        from src.modules.sidecars.performance.common.db import Settings

        existing = Settings(key='retention_epochs', value=100)
        mock_session.get.return_value = existing

        db.set_retention_epochs(200)

        assert existing.value == 200
        mock_session.commit.assert_called_once()

    def test_set_retention_epochs_creates_when_missing(self, db, mock_session):
        mock_session.get.return_value = None

        db.set_retention_epochs(300)

        mock_session.add.assert_called_once()
        added = mock_session.add.call_args[0][0]
        assert added.key == 'retention_epochs'
        assert added.value == 300
        mock_session.commit.assert_called_once()

    def test_set_retention_epochs_rejects_negative(self, db):
        with pytest.raises(ValueError, match="retention_epochs must be positive"):
            db.set_retention_epochs(-1)

    def test_set_retention_epochs_rejects_zero(self, db):
        with pytest.raises(ValueError, match="retention_epochs must be positive"):
            db.set_retention_epochs(0)

    def test_seed_settings_creates_when_missing(self, db, mock_session, monkeypatch):
        mock_session.get.return_value = None

        db._seed_settings()

        mock_session.add.assert_called_once()
        added = mock_session.add.call_args[0][0]
        assert added.key == 'retention_epochs'
        assert added.value == RETENTION_EPOCHS_DEFAULT
        mock_session.commit.assert_called_once()

    def test_seed_settings_skips_when_exists(self, db, mock_session):
        mock_session.get.return_value = Settings(key='retention_epochs', value=99)

        db._seed_settings()

        mock_session.add.assert_not_called()
        mock_session.commit.assert_not_called()


class TestStoreEpoch:
    def test_store_epoch_creates_new_duty(self, db, mock_session):
        mock_session.get.return_value = None
        att_misses = {1, 2, 3}
        proposals = [
            ProposalDuty(validator_index=10, is_proposed=True),
            ProposalDuty(validator_index=11, is_proposed=False),
            ProposalDuty(validator_index=12, is_proposed=True),
        ]
        syncs = [
            SyncDuty(validator_index=20, missed_count=5),
            SyncDuty(validator_index=21, missed_count=0),
            SyncDuty(validator_index=22, missed_count=3),
        ]

        with patch.object(db, '_prune'):
            db.store_epoch(EpochNumber(100), att_misses, proposals, syncs)

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        added_duty = mock_session.add.call_args[0][0]
        assert added_duty.epoch == 100
        assert sorted(added_duty.attestations) == [1, 2, 3]
        assert added_duty.proposals_vids == [10, 11, 12]
        assert added_duty.proposals_flags == [True, False, True]
        assert added_duty.syncs_vids == [20, 21, 22]
        assert added_duty.syncs_misses == [5, 0, 3]

    def test_store_epoch_updates_existing_duty(self, db, mock_session):
        existing = Duty(
            epoch=100,
            attestations=[1],
            proposals_vids=[5],
            proposals_flags=[False],
            syncs_vids=[10],
            syncs_misses=[1],
        )
        mock_session.get.return_value = existing
        att_misses = {7, 8}
        proposals = [ProposalDuty(validator_index=50, is_proposed=True)]
        syncs = [SyncDuty(validator_index=60, missed_count=3)]

        with patch.object(db, '_prune'):
            db.store_epoch(EpochNumber(100), att_misses, proposals, syncs)

        mock_session.add.assert_not_called()
        mock_session.commit.assert_called_once()
        assert sorted(existing.attestations) == [7, 8]
        assert existing.proposals_vids == [50]
        assert existing.proposals_flags == [True]
        assert existing.syncs_vids == [60]
        assert existing.syncs_misses == [3]


class TestPrune:
    def test_prune_skips_when_threshold_negative(self, db, mock_session):
        db.get_retention_epochs = Mock(return_value=1000)
        db.max_epoch = Mock(return_value=500)

        db._prune(EpochNumber(500))

        mock_session.exec.assert_not_called()

    def test_prune_removes_old_epochs_using_max_epoch_anchor(self, db, mock_session):
        db.get_retention_epochs = Mock(return_value=10)
        db.max_epoch = Mock(return_value=100)

        db._prune(EpochNumber(5))

        mock_session.exec.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_prune_falls_back_to_current_epoch_when_db_empty(self, db, mock_session):
        db.get_retention_epochs = Mock(return_value=10)
        db.max_epoch = Mock(return_value=None)

        db._prune(EpochNumber(100))

        mock_session.exec.assert_called_once()
        mock_session.commit.assert_called_once()


class TestIsRangeAvailable:
    def test_raises_on_invalid_range(self, db):
        with pytest.raises(ValueError, match="Invalid epoch range"):
            db.is_range_available(EpochNumber(20), EpochNumber(10))

    def test_returns_true_when_all_present(self, db, mock_session):
        mock_session.exec.return_value.one.return_value = 11  # 10..20 inclusive = 11 epochs

        result = db.is_range_available(EpochNumber(10), EpochNumber(20))

        assert result is True

    def test_returns_false_when_incomplete(self, db, mock_session):
        mock_session.exec.return_value.one.return_value = 5  # only 5 out of 11

        result = db.is_range_available(EpochNumber(10), EpochNumber(20))

        assert result is False


class TestMissingEpochsIn:
    def test_raises_on_invalid_range(self, db):
        with pytest.raises(ValueError, match="Invalid epoch range"):
            db.missing_epochs_in(EpochNumber(20), EpochNumber(10))

    def test_returns_missing_epochs(self, db, mock_session):
        # Range 10..15, only 10, 12, 14 present
        mock_session.exec.return_value.all.return_value = [10, 12, 14]

        result = db.missing_epochs_in(EpochNumber(10), EpochNumber(15))

        assert result == [EpochNumber(11), EpochNumber(13), EpochNumber(15)]

    def test_returns_empty_when_complete(self, db, mock_session):
        mock_session.exec.return_value.all.return_value = [10, 11, 12, 13, 14, 15]

        result = db.missing_epochs_in(EpochNumber(10), EpochNumber(15))

        assert result == []


class TestGetEpochData:
    def test_returns_duty_when_found(self, db, mock_session):
        duty = Duty(
            epoch=100,
            attestations=[1, 2],
            proposals_vids=[3],
            proposals_flags=[True],
            syncs_vids=[4],
            syncs_misses=[0],
        )
        mock_session.get.return_value = duty

        result = db.get_epoch_data(EpochNumber(100))

        assert result is duty
        mock_session.get.assert_called_once_with(Duty, EpochNumber(100))

    def test_returns_none_when_not_found(self, db, mock_session):
        mock_session.get.return_value = None

        result = db.get_epoch_data(EpochNumber(999))

        assert result is None


class TestHasEpoch:
    def test_has_epoch_true(self, db, mock_session):
        mock_session.exec.return_value.one.return_value = True

        assert db.has_epoch(EpochNumber(100)) is True

    def test_has_epoch_false(self, db, mock_session):
        mock_session.exec.return_value.one.return_value = False

        assert db.has_epoch(EpochNumber(100)) is False


class TestMinMaxEpoch:
    def test_min_epoch_empty_db(self, db, mock_session):
        mock_session.exec.return_value.first.return_value = None

        result = db.min_epoch()

        assert result is None

    def test_min_epoch_non_empty(self, db, mock_session):
        mock_session.exec.return_value.first.return_value = 5

        result = db.min_epoch()

        assert result == EpochNumber(5)

    def test_max_epoch_empty_db(self, db, mock_session):
        mock_session.exec.return_value.first.return_value = None

        result = db.max_epoch()

        assert result is None

    def test_max_epoch_non_empty(self, db, mock_session):
        mock_session.exec.return_value.first.return_value = 10

        result = db.max_epoch()

        assert result == EpochNumber(10)


class TestCounts:
    def test_epochs_count(self, db, mock_session):
        mock_session.exec.return_value.one.return_value = 42

        result = db.epochs_count()

        assert result == 42

    def test_demands_count(self, db, mock_session):
        mock_session.exec.return_value.one.return_value = 3

        result = db.demands_count()

        assert result == 3


class TestGetDemands:
    def test_get_epochs_demand_found(self, db, mock_session):
        demand = EpochsDemand(consumer='test', from_epoch=1, to_epoch=10, updated_at=datetime(2024, 1, 1, tzinfo=UTC))
        mock_session.get.return_value = demand

        result = db.get_epochs_demand('test')

        assert result is demand
        mock_session.get.assert_called_once_with(EpochsDemand, 'test')

    def test_get_epochs_demand_not_found(self, db, mock_session):
        mock_session.get.return_value = None

        result = db.get_epochs_demand('nonexistent')

        assert result is None

    def test_get_epochs_demands_empty(self, db, mock_session):
        mock_session.exec.return_value.all.return_value = []

        result = db.get_epochs_demands()

        assert result == []

    def test_get_epochs_demands_with_data(self, db, mock_session):
        demands = [
            EpochsDemand(consumer='a', from_epoch=1, to_epoch=10, updated_at=datetime(2024, 1, 1, tzinfo=UTC)),
            EpochsDemand(consumer='b', from_epoch=5, to_epoch=15, updated_at=datetime(2024, 2, 1, tzinfo=UTC)),
        ]
        mock_session.exec.return_value.all.return_value = demands

        result = db.get_epochs_demands()

        assert result == demands
        assert len(result) == 2

    def test_count_stored_epochs_in_range(self, db, mock_session):
        mock_session.exec.return_value.one.return_value = 7

        result = db.count_stored_epochs_in_range(EpochNumber(10), EpochNumber(20))

        assert result == 7
        mock_session.exec.assert_called_once()

    def test_count_stored_epochs_in_range_invalid_range(self, db, mock_session):
        with pytest.raises(ValueError, match='Invalid epoch range'):
            db.count_stored_epochs_in_range(EpochNumber(20), EpochNumber(10))
        mock_session.exec.assert_not_called()

    def test_get_epochs_demands_max_updated_at(self, db, mock_session):
        mock_session.exec.return_value.one.return_value = 500

        result = db.get_epochs_demands_max_updated_at()

        assert result == 500


class TestGetSession:
    def test_get_session_creates_session(self, db):
        """Test that get_session creates a Session from the engine"""
        with (
            patch('src.modules.sidecars.performance.common.db.create_engine'),
            patch('src.modules.sidecars.performance.common.db.SQLModel'),
        ):
            instance = DutiesDB()

        # Call the REAL get_session (not the mocked one from the db fixture)
        with patch('src.modules.sidecars.performance.common.db.Session') as mock_session_class:
            mock_session_class.return_value = mock_session
            session = instance.get_session()

        mock_session_class.assert_called_once_with(instance.engine, expire_on_commit=False)
        assert session is mock_session


class TestGetEpochsData:
    def test_get_epochs_data_returns_duties(self, db, mock_session):
        duties = [
            Duty(
                epoch=10,
                attestations=[1],
                proposals_vids=[2],
                proposals_flags=[True],
                syncs_vids=[3],
                syncs_misses=[0],
            ),
            Duty(
                epoch=11,
                attestations=[],
                proposals_vids=[],
                proposals_flags=[],
                syncs_vids=[],
                syncs_misses=[],
            ),
        ]
        mock_session.exec.return_value.all.return_value = duties

        result = db.get_epochs_data(EpochNumber(10), EpochNumber(11))

        assert result == duties
        assert len(result) == 2
        mock_session.exec.assert_called_once()

    def test_get_complete_epochs_data_returns_duties_when_range_is_complete(self, db):
        duties = [
            Duty(
                epoch=10,
                attestations=[1],
                proposals_vids=[2],
                proposals_flags=[True],
                syncs_vids=[3],
                syncs_misses=[0],
            ),
            Duty(
                epoch=11,
                attestations=[],
                proposals_vids=[],
                proposals_flags=[],
                syncs_vids=[],
                syncs_misses=[],
            ),
        ]
        db.get_epochs_data = Mock(return_value=duties)

        result = db.get_complete_epochs_data(EpochNumber(10), EpochNumber(11))

        assert result == duties
        db.get_epochs_data.assert_called_once_with(EpochNumber(10), EpochNumber(11))

    def test_get_complete_epochs_data_raises_when_range_has_gaps(self, db):
        db.get_epochs_data = Mock(
            return_value=[
                Duty(
                    epoch=10,
                    attestations=[],
                    proposals_vids=[],
                    proposals_flags=[],
                    syncs_vids=[],
                    syncs_misses=[],
                ),
                Duty(
                    epoch=12,
                    attestations=[],
                    proposals_vids=[],
                    proposals_flags=[],
                    syncs_vids=[],
                    syncs_misses=[],
                ),
                Duty(
                    epoch=14,
                    attestations=[],
                    proposals_vids=[],
                    proposals_flags=[],
                    syncs_vids=[],
                    syncs_misses=[],
                ),
            ]
        )

        with pytest.raises(IncompleteEpochRangeError, match="Incomplete epoch range"):
            db.get_complete_epochs_data(EpochNumber(10), EpochNumber(15))

        db.get_epochs_data.assert_called_once_with(EpochNumber(10), EpochNumber(15))
