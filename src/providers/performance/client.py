from collections.abc import Iterator
from itertools import batched

from src import variables
from src.metrics.prometheus.basic import PERFORMANCE_REQUESTS_DURATION
from src.modules.sidecars.performance.common.db import Duty, EpochsDemand
from src.providers.http_provider import (
    HTTPProvider,
    NotOkResponse,
    data_is_bool,
    data_is_int,
    data_is_list,
)
from src.types import EpochNumber
from src.utils.range import sequence


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

    def get_epochs_data(self, from_epoch: EpochNumber, to_epoch: EpochNumber) -> Iterator[Duty]:
        batch_size = variables.PERFORMANCE_COLLECTOR_EPOCHS_BATCH_SIZE
        for epochs_batch in batched(sequence(from_epoch, to_epoch), batch_size, strict=False):
            data, _ = self._get(
                self.API_EPOCHS_DATA,
                query_params={'from': epochs_batch[0], 'to': epochs_batch[-1]},
                validate_response=data_is_list,
            )
            for item in data:
                yield Duty.model_validate(item)

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
