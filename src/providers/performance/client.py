from eth_typing import HexStr

from src.metrics.prometheus.basic import PERFORMANCE_REQUESTS_DURATION
from src.modules.performance_collector.codec import EpochDataCodec, EpochData
from src.providers.http_provider import HTTPProvider, NotOkResponse, data_is_dict
from src.types import EpochNumber


class PerformanceClientError(NotOkResponse):
    pass


class PerformanceClient(HTTPProvider):
    PROVIDER_EXCEPTION = PerformanceClientError
    PROMETHEUS_HISTOGRAM = PERFORMANCE_REQUESTS_DURATION

    API_EPOCHS_CHECK = 'epochs/check'
    API_EPOCHS_MISSING = 'epochs/missing'
    API_EPOCHS_BLOB = 'epochs/blob'

    def is_range_available(self, l_epoch: int, r_epoch: int) -> bool:
        data, _ = self._get(
            self.API_EPOCHS_CHECK,
            query_params={'from': l_epoch, 'to': r_epoch},
            retval_validator=data_is_dict,
        )
        return data['result']

    def missing_epochs_in(self, l_epoch: int, r_epoch: int) -> list[EpochNumber]:
        data, _ = self._get(
            self.API_EPOCHS_MISSING,
            query_params={'from': l_epoch, 'to': r_epoch},
            retval_validator=data_is_dict,
        )
        return data['result']

    def get_epoch_blobs(self, l_epoch: int, r_epoch: int) -> list[HexStr | None]:
        data, _ = self._get(
            self.API_EPOCHS_BLOB,
            query_params={'from': l_epoch, 'to': r_epoch},
            retval_validator=data_is_dict,
        )
        return data['result']

    def get_epoch_blob(self, epoch: int) -> HexStr | None:
        data, _ = self._get(
            self.API_EPOCHS_BLOB + f"/{epoch}",
            retval_validator=data_is_dict,
        )
        return data['result']

    def get_epochs(self, l_epoch: int, r_epoch: int) -> list[EpochData]:
        epochs_data = self.get_epoch_blobs(l_epoch, r_epoch)
        return [
            EpochDataCodec.decode(bytes.fromhex(blob))
            if (blob := epoch_data['blob']) else None
            for epoch_data in epochs_data
        ]

    def get_epoch(self, epoch: int) -> EpochData | None:
        blob = self.get_epoch_blob(epoch)
        return EpochDataCodec.decode(bytes.fromhex(blob)) if blob else None
