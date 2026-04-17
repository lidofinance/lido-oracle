from unittest.mock import Mock

import pytest

from modules.sidecars.performance.common.db import Duty, EpochsDemand
from providers.http_provider import data_is_bool, data_is_int, data_is_list
from providers.performance.client import PerformanceClient, PerformanceClientError
from type_aliases import EpochNumber


HOST = "http://performance.local"


@pytest.fixture()
def client() -> PerformanceClient:
    return PerformanceClient(
        hosts=[HOST],
        request_timeout=5,
        retry_total=0,
        retry_backoff_factor=0,
    )


@pytest.mark.unit
def test_is_range_available_true(client: PerformanceClient):
    client._get = Mock(return_value=(True, {}))

    result = client.is_range_available(EpochNumber(100), EpochNumber(200))

    assert result is True
    client._get.assert_called_once_with(
        "v1/check-epochs",
        query_params={"from": 100, "to": 200},
        validate_response=data_is_bool,
    )


@pytest.mark.unit
def test_is_range_available_false(client: PerformanceClient):
    client._get = Mock(return_value=(False, {}))

    result = client.is_range_available(EpochNumber(100), EpochNumber(200))

    assert result is False


@pytest.mark.unit
def test_get_epoch_data_returns_duty(client: PerformanceClient):
    raw = {
        "epoch": 100,
        "attestations": [1, 2],
        "proposals_vids": [],
        "proposals_flags": [],
        "syncs_vids": [],
        "syncs_misses": [],
    }
    client._get = Mock(return_value=(raw, {}))

    result = client.get_epoch_data(EpochNumber(100))

    assert result == Duty(epoch=100, attestations=[1, 2])
    client._get.assert_called_once_with("v1/epochs/100")


@pytest.mark.unit
def test_get_epoch_data_returns_none_for_empty(client: PerformanceClient):
    client._get = Mock(return_value=(None, {}))

    result = client.get_epoch_data(EpochNumber(100))

    assert result is None


@pytest.mark.unit
def test_get_epochs_data(client: PerformanceClient):
    raw = [
        {
            "epoch": 100,
            "attestations": [],
            "proposals_vids": [],
            "proposals_flags": [],
            "syncs_vids": [],
            "syncs_misses": [],
        },
        {
            "epoch": 101,
            "attestations": [],
            "proposals_vids": [],
            "proposals_flags": [],
            "syncs_vids": [],
            "syncs_misses": [],
        },
    ]
    client._get = Mock(return_value=(raw, {}))

    result = client.get_epochs_data(EpochNumber(100), EpochNumber(101))

    assert result == [Duty(epoch=100), Duty(epoch=101)]
    client._get.assert_called_once_with(
        "v1/epochs",
        query_params={"from": 100, "to": 101},
        validate_response=data_is_list,
    )


@pytest.mark.unit
def test_get_epochs_demand_returns_demand(client: PerformanceClient):
    raw = {"consumer": "csm", "from_epoch": 10, "to_epoch": 20, "updated_at": None}
    client._get = Mock(return_value=(raw, {}))

    result = client.get_epochs_demand("csm")

    assert result == EpochsDemand(consumer="csm", from_epoch=10, to_epoch=20, updated_at=None)
    client._get.assert_called_once_with("v1/demands/csm")


@pytest.mark.unit
def test_get_epochs_demand_returns_none_for_empty(client: PerformanceClient):
    client._get = Mock(return_value=(None, {}))

    result = client.get_epochs_demand("csm")

    assert result is None


@pytest.mark.unit
def test_get_stored_epochs_count_returns_count(client: PerformanceClient):
    raw = 5
    client._get = Mock(return_value=(raw, {}))

    result = client.get_stored_epochs_count(EpochNumber(10), EpochNumber(20))

    assert result == 5
    client._get.assert_called_once_with(
        "v1/epochs/stored-count",
        query_params={"from": 10, "to": 20},
        validate_response=data_is_int,
    )


@pytest.mark.unit
def test_get_stored_epochs_count_raises_on_non_int(client: PerformanceClient):
    client._get = Mock(side_effect=ValueError("Expected int response from v1/epochs/stored-count"))

    with pytest.raises(ValueError, match="Expected int response"):
        client.get_stored_epochs_count(EpochNumber(10), EpochNumber(20))


@pytest.mark.unit
def test_post_epochs_demand(client: PerformanceClient):
    client._post = Mock(return_value=({}, {}))

    client.post_epochs_demand("csm", EpochNumber(10), EpochNumber(20))

    client._post.assert_called_once_with(
        "v1/demands",
        body_data={"consumer": "csm", "from_epoch": 10, "to_epoch": 20},
    )


@pytest.mark.unit
def test_delete_epochs_demand(client: PerformanceClient):
    client._delete = Mock(return_value=({}, {}))

    client.delete_epochs_demand("csm")

    client._delete.assert_called_once_with("v1/demands/csm")


@pytest.mark.unit
def test_provider_exception_is_performance_client_error():
    assert PerformanceClient.PROVIDER_EXCEPTION is PerformanceClientError
    assert issubclass(PerformanceClientError, Exception)
