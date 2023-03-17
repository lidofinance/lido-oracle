from functools import lru_cache
from time import sleep
from typing import Optional, cast

from src.metrics.prometheus.basic import KEYS_API_REQUESTS_DURATION, KEYS_API_LATEST_BLOCKNUMBER
from src.providers.http_provider import HTTPProvider
from src.providers.keys.typings import LidoKey
from src.typings import BlockStamp
from src.utils.dataclass import list_of_dataclasses


class KeysOutdatedException(Exception):
    pass


class KeysAPIClient(HTTPProvider):

    RETRY_COUNT = 5
    REQUEST_TIMEOUT = 10
    SLEEP_SECONDS = 12

    PROMETHEUS_HISTOGRAM = KEYS_API_REQUESTS_DURATION

    ALL_KEYS = 'v1/keys'

    def _get_with_blockstamp(self, url: str, blockstamp: BlockStamp, params: Optional[dict] = None) -> dict | list:
        """
        Returns response if blockstamp < blockNumber from response
        """
        for i in range(self.RETRY_COUNT):
            data, meta = self._get(url, query_params=params)
            blocknumber_meta = meta['meta']['elBlockSnapshot']['blockNumber']
            KEYS_API_LATEST_BLOCKNUMBER.set(blocknumber_meta)
            if blocknumber_meta >= blockstamp.block_number:
                return data

            if i != self.RETRY_COUNT - 1:
                sleep(self.SLEEP_SECONDS)

        raise KeysOutdatedException(f'Keys API Service stuck, no updates for {self.SLEEP_SECONDS * self.RETRY_COUNT} seconds.')

    @lru_cache(maxsize=1)
    @list_of_dataclasses(LidoKey.from_response)
    def get_all_lido_keys(self, blockstamp: BlockStamp) -> list[dict]:
        """Docs: https://keys-api.lido.fi/api/static/index.html#/sr-module-keys/SRModulesKeysController_getGroupedByModuleKeys"""
        return cast(list[dict], self._get_with_blockstamp(self.ALL_KEYS, blockstamp))
