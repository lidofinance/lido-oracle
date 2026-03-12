from unittest.mock import MagicMock, Mock, patch

import pytest
from starlette.testclient import TestClient

from src.modules.sidecars.performance.common.db import DutiesDB, Duty, EpochsDemand
from src.modules.sidecars.performance.web.server import app, get_db


pytestmark = pytest.mark.unit


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    return session


@pytest.fixture
def mock_db(mock_session):
    db = MagicMock(spec=DutiesDB)
    db.get_session.return_value = mock_session
    return db


@pytest.fixture
def client(mock_db):
    app.dependency_overrides[get_db] = lambda: mock_db
    with (
        patch(
            "src.modules.sidecars.performance.web.server.DutiesDB",
            return_value=mock_db,
        ),
        TestClient(app, raise_server_exceptions=False) as c,
    ):
        yield c
    app.dependency_overrides.clear()


class TestHealth:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_returns_503_on_db_failure(self, client, mock_session):
        mock_session.exec.side_effect = Exception("some error")
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json() == {"detail": "Database connection failed: some error"}


class TestCheckEpochs:
    def test_returns_true_when_available(self, client, mock_db):
        mock_db.is_range_available.return_value = True
        response = client.get("/v1/check-epochs", params={"from": 10, "to": 20})
        assert response.status_code == 200
        assert response.json() is True

    def test_returns_false_when_not_available(self, client, mock_db):
        mock_db.is_range_available.return_value = False
        response = client.get("/v1/check-epochs", params={"from": 10, "to": 20})
        assert response.status_code == 200
        assert response.json() is False

    def test_rejects_invalid_range(self, client):
        response = client.get("/v1/check-epochs", params={"from": 20, "to": 10})
        assert response.status_code == 422


class TestMissingEpochs:
    def test_returns_missing_list(self, client, mock_db):
        mock_db.missing_epochs_in.return_value = [11, 13]
        response = client.get("/v1/missing-epochs", params={"from": 10, "to": 15})
        assert response.status_code == 200
        assert response.json() == [11, 13]

    def test_returns_empty(self, client, mock_db):
        mock_db.missing_epochs_in.return_value = []
        response = client.get("/v1/missing-epochs", params={"from": 10, "to": 15})
        assert response.status_code == 200
        assert response.json() == []

    def test_rejects_range_too_large(self, client):
        response = client.get("/v1/missing-epochs", params={"from": 0, "to": 100000})
        assert response.status_code == 422


class TestEpochsData:
    def test_returns_duties(self, client, mock_db):
        duties = [
            Duty(
                epoch=10,
                attestations=[1, 2],
                proposals_vids=[3],
                proposals_flags=[True],
                syncs_vids=[4],
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
        mock_db.get_epochs_data.return_value = duties
        response = client.get("/v1/epochs", params={"from": 10, "to": 11})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["epoch"] == 10
        assert data[1]["epoch"] == 11

    def test_returns_empty(self, client, mock_db):
        mock_db.get_epochs_data.return_value = []
        response = client.get("/v1/epochs", params={"from": 10, "to": 11})
        assert response.status_code == 200
        assert response.json() == []

    def test_rejects_range_too_large(self, client):
        response = client.get("/v1/epochs", params={"from": 0, "to": 100000})
        assert response.status_code == 422


class TestEpochData:
    def test_returns_duty_when_found(self, client, mock_db):
        duty = Duty(
            epoch=10,
            attestations=[],
            proposals_vids=[],
            proposals_flags=[],
            syncs_vids=[],
            syncs_misses=[],
        )
        mock_db.get_epoch_data.return_value = duty
        response = client.get("/v1/epochs/10")
        assert response.status_code == 200
        assert response.json()["epoch"] == 10

    def test_returns_null_when_not_found(self, client, mock_db):
        mock_db.get_epoch_data.return_value = None
        response = client.get("/v1/epochs/10")
        assert response.status_code == 200
        assert response.json() is None

    def test_rejects_negative_epoch(self, client):
        response = client.get("/v1/epochs/-1")
        assert response.status_code == 422


class TestDemands:
    def test_returns_all_demands(self, client, mock_db):
        demands = [
            EpochsDemand(consumer="consumer1", from_epoch=10, to_epoch=20, updated_at=1000),
            EpochsDemand(consumer="consumer2", from_epoch=30, to_epoch=40, updated_at=2000),
        ]
        mock_db.get_epochs_demands.return_value = demands
        response = client.get("/v1/demands")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["consumer"] == "consumer1"
        assert data[1]["consumer"] == "consumer2"

    def test_returns_single_demand(self, client, mock_db):
        demand = EpochsDemand(consumer="consumer1", from_epoch=10, to_epoch=20, updated_at=1000)
        mock_db.get_epochs_demand.return_value = demand
        response = client.get("/v1/demands/consumer1")
        assert response.status_code == 200
        data = response.json()
        assert data["consumer"] == "consumer1"
        assert data["from_epoch"] == 10
        assert data["to_epoch"] == 20

    def test_returns_null_when_not_found(self, client, mock_db):
        mock_db.get_epochs_demand.return_value = None
        response = client.get("/v1/demands/unknown")
        assert response.status_code == 200
        assert response.json() is None

    def test_rejects_blank_consumer(self, client):
        response = client.get("/v1/demands/%20%20%20")
        assert response.status_code == 422


class TestSetDemand:
    def test_creates_demand(self, client, mock_db):
        demand = EpochsDemand(consumer="consumer1", from_epoch=10, to_epoch=20, updated_at=1000)
        mock_db.store_demand.return_value = demand
        response = client.post(
            "/v1/demands",
            json={"consumer": "consumer1", "from_epoch": 10, "to_epoch": 20},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["consumer"] == "consumer1"
        assert data["from_epoch"] == 10
        assert data["to_epoch"] == 20
        assert data["updated_at"] == 1000

    def test_rejects_invalid_payload(self, client):
        response = client.post(
            "/v1/demands",
            json={"consumer": "   ", "from_epoch": 20, "to_epoch": 10},
        )
        assert response.status_code == 422


class TestDeleteDemand:
    def test_succeeds(self, client, mock_db):
        demand = EpochsDemand(consumer="consumer1", from_epoch=10, to_epoch=20, updated_at=1000)
        mock_db.get_epochs_demand.return_value = demand
        response = client.delete("/v1/demands/consumer1")
        assert response.status_code == 200
        data = response.json()
        assert data["consumer"] == "consumer1"
        mock_db.delete_demand.assert_called_once_with("consumer1")

    def test_returns_404_when_not_found(self, client, mock_db):
        mock_db.get_epochs_demand.return_value = None
        response = client.delete("/v1/demands/unknown")
        assert response.status_code == 404
