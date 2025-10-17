from src.metrics.prometheus.basic import PERFORMANCE_REQUESTS_DURATION
from src.modules.performance_collector.codec import EpochBlobCodec, ProposalDuty, SyncDuty, EpochBlob
from src.providers.http_provider import HTTPProvider, NotOkResponse, data_is_dict


class PerformanceClientError(NotOkResponse):
    pass


# TODO: dataclasses and types ???


class PerformanceClient(HTTPProvider):
    PROVIDER_EXCEPTION = PerformanceClientError
    PROMETHEUS_HISTOGRAM = PERFORMANCE_REQUESTS_DURATION

    API_EPOCHS_CHECK = 'epochs/check'
    API_EPOCHS_MISSING = 'epochs/missing'
    API_EPOCHS_BLOB = 'epochs/blob'

    def is_range_available(self, l_epoch: int, r_epoch: int) -> bool:
        data, _ = self._get(
            self.API_EPOCHS_CHECK,
            query_params={'from': int(l_epoch), 'to': int(r_epoch)},
            retval_validator=data_is_dict,
        )
        return data['result']

    def missing_epochs_in(self, l_epoch: int, r_epoch: int) -> list[int]:
        data, _ = self._get(
            self.API_EPOCHS_MISSING,
            query_params={'from': int(l_epoch), 'to': int(r_epoch)},
            retval_validator=data_is_dict,
        )
        return data['result']

    def get_epoch_blobs(self, l_epoch: int, r_epoch: int) -> list[dict[str, str | None]]:
        data, _ = self._get(
            self.API_EPOCHS_BLOB,
            query_params={'from': int(l_epoch), 'to': int(r_epoch)},
            retval_validator=data_is_dict,
        )
        return data['result']

    def get_epochs(self, l_epoch: int, r_epoch: int) -> list[tuple[set[int], list[ProposalDuty], list[SyncDuty]]]:
        epochs_data = self.get_epoch_blobs(l_epoch, r_epoch)
        return [EpochBlobCodec.decode(bytes.fromhex(epoch_data['blob'])) for epoch_data in epochs_data]

    def get_epoch(self, epoch: int) -> EpochBlob | None:
        res = self.get_epochs(epoch, epoch)
        return res[0]
