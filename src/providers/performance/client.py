from metrics.prometheus.basic import PERFORMANCE_REQUESTS_DURATION
from modules.sidecars.performance.common.db import Duty, EpochsDemand
from providers.http_provider import (
    HTTPProvider,
    NotOkResponse,
    data_is_bool,
    data_is_int,
    data_is_list,
)
from type_aliases import EpochNumber


class PerformanceClientError(NotOkResponse):
    pass


class PerformanceClient(HTTPProvider):
    PROVIDER_EXCEPTION = PerformanceClientError
    PROMETHEUS_HISTOGRAM = PERFORMANCE_REQUESTS_DURATION

    API_PREFIX = 'v1'
    API_EPOCHS_CHECK = f'{API_PREFIX}/check-epochs'
    API_EPOCHS_DATA = f'{API_PREFIX}/epochs'
    API_EPOCHS_STORED_COUNT = f'{API_EPOCHS_DATA}/stored-count'
    API_EPOCHS_DEMAND = f'{API_PREFIX}/demands'

    def is_range_available(self, from_epoch: EpochNumber, to_epoch: EpochNumber) -> bool:
        data, _ = self._get(
            self.API_EPOCHS_CHECK,
            query_params={'from': from_epoch, 'to': to_epoch},
            validate_response=data_is_bool,
        )
        return data

    def get_epoch_data(self, epoch: EpochNumber) -> Duty | None:
        data, _ = self._get(self.API_EPOCHS_DATA + f"/{epoch}")
        return Duty.model_validate(data) if data else None

    def get_epochs_data(self, from_epoch: EpochNumber, to_epoch: EpochNumber) -> list[Duty]:
        data, _ = self._get(
            self.API_EPOCHS_DATA,
            query_params={'from': from_epoch, 'to': to_epoch},
            validate_response=data_is_list,
        )
        return [Duty.model_validate(item) for item in data]

    def get_epochs_demand(self, consumer: str) -> EpochsDemand | None:
        data, _ = self._get(self.API_EPOCHS_DEMAND + f"/{consumer}")
        return EpochsDemand.model_validate(data) if data else None

    def get_stored_epochs_count(self, from_epoch: EpochNumber, to_epoch: EpochNumber) -> int:
        data, _ = self._get(
            self.API_EPOCHS_STORED_COUNT,
            query_params={'from': from_epoch, 'to': to_epoch},
            validate_response=data_is_int,
        )
        return data

    def post_epochs_demand(self, consumer: str, from_epoch: EpochNumber, to_epoch: EpochNumber) -> None:
        self._post(
            self.API_EPOCHS_DEMAND,
            body_data={'consumer': consumer, 'from_epoch': from_epoch, 'to_epoch': to_epoch},
        )

    def delete_epochs_demand(self, consumer: str) -> None:
        self._delete(self.API_EPOCHS_DEMAND + f"/{consumer}")
