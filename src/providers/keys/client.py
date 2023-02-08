from functools import lru_cache
from time import sleep
from typing import List, Optional

from src.metrics.prometheus.basic import KEYS_API_REQUESTS_DURATION, KEYS_API_REQUESTS
from src.providers.http_provider import HTTPProvider
from src.providers.keys.typings import LidoKey, OperatorResponse
from src.typings import BlockStamp
from src.utils.freeze_decorator import freezeargs


class KeysOutdatedException(Exception):
    pass


class KeysAPIClient(HTTPProvider):
    RETRY_COUNT = 10
    REQUEST_TIMEOUT = 60
    SLEEP_SECONDS = 10

    PROMETHEUS_HISTOGRAM = KEYS_API_REQUESTS_DURATION
    PROMETHEUS_COUNTER = KEYS_API_REQUESTS

    ALL_KEYS = 'v1/keys'
    ALL_OPERATORS = 'v1/operators'

    def _get_with_blockstamp(self, url: str, blockstamp: BlockStamp, params: Optional[dict] = None) -> dict:
        """
        Returns response if blockstamp < blockNumber from response
        """
        for i in range(self.RETRY_COUNT):
            data, meta = self._get(url, params)
            if meta['meta']['elBlockSnapshot']['blockNumber'] >= blockstamp['block_number']:
                return data

            if i != self.RETRY_COUNT - 1:
                sleep(self.SLEEP_SECONDS)

        raise KeysOutdatedException(f'Keys API Service stucked, no updates for {self.SLEEP_SECONDS * self.RETRY_COUNT} seconds.')

    @freezeargs
    @lru_cache(maxsize=1)
    def get_all_lido_keys(self, blockstamp: BlockStamp) -> List[LidoKey]:
        """Docs: https://keys-api.testnet.fi/api/static/index.html#/sr-module-keys/SRModulesKeysController_getGroupedByModuleKeys"""
        return self._get_with_blockstamp(self.ALL_KEYS, blockstamp)

    @freezeargs
    @lru_cache(maxsize=1)
    def get_operators(self, blockstamp: BlockStamp) -> List[OperatorResponse]:
        """Docs: https://keys-api.testnet.fi/api/static/index.html#/operators/SRModulesOperatorsController_get"""
        return self._get_with_blockstamp(self.ALL_OPERATORS, blockstamp)
