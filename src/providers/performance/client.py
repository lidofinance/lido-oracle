from src.metrics.prometheus.basic import PERFORMANCE_REQUESTS_DURATION
from src.modules.sidecars.performance.common.db import Duty, EpochsDemand
from src.providers.http_provider import (
    HTTPProvider,
    NotOkResponse,
    data_is_list,
)
from src.types import EpochNumber


class PerformanceClientError(NotOkResponse):
    pass


class PerformanceClient(HTTPProvider):
    PROVIDER_EXCEPTION = PerformanceClientError
    PROMETHEUS_HISTOGRAM = PERFORMANCE_REQUESTS_DURATION

    API_EPOCHS_CHECK = 'check-epochs'
    API_EPOCHS_DATA = 'epochs'
    API_EPOCHS_DEMAND = 'demands'

    def is_range_available(self, from_epoch: EpochNumber, to_epoch: EpochNumber) -> bool:
        data, _ = self._get(
            self.API_EPOCHS_CHECK,
            query_params={'from': from_epoch, 'to': to_epoch},
        )
        return bool(data)

    def get_epoch_data(self, epoch: EpochNumber) -> Duty | None:
        data, _ = self._get(
            self.API_EPOCHS_DATA + f"/{epoch}",
        )
        return Duty.model_validate(data) if data else None

    def get_epochs_data(self, l_epoch: EpochNumber, r_epoch: EpochNumber) -> list[Duty]:
        data, _ = self._get(
            self.API_EPOCHS_DATA,
            query_params={'from': l_epoch, 'to': r_epoch},
            retval_validator=data_is_list,
        )
        return [Duty.model_validate(item) for item in data] if data else []

    def get_epochs_demand(self, consumer: str) -> EpochsDemand | None:
        data, _ = self._get(
            self.API_EPOCHS_DEMAND + f"/{consumer}",
        )
        return EpochsDemand.model_validate(data) if data else None

    def post_epochs_demand(self, consumer: str, from_epoch: EpochNumber, to_epoch: EpochNumber) -> None:
        self._post(
            self.API_EPOCHS_DEMAND,
            body_data={'consumer': consumer, 'from_epoch': from_epoch, 'to_epoch': to_epoch},
        )

    def delete_epochs_demand(self, consumer: str) -> None:
        self._delete(
            self.API_EPOCHS_DEMAND,
            query_params={'consumer': consumer},
        )
