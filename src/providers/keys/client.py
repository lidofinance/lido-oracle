from functools import lru_cache
from time import sleep
from typing import List

from src.metrics.prometheus.basic import KEYS_API_REQUESTS_DURATION, KEYS_API_REQUESTS
from src.providers.http_provider import HTTPProvider
from src.providers.keys.typings import LidoKey
from src.typings import BlockStamp


class KeysOutdatedException(Exception):
    pass


class KeysAPIClient(HTTPProvider):
    RETRY_COUNT = 10
    REQUEST_TIMEOUT = 60
    SLEEP_SECONDS = 10

    PROMETHEUS_HISTOGRAM = KEYS_API_REQUESTS_DURATION
    PROMETHEUS_COUNTER = KEYS_API_REQUESTS

    ALL_KEYS = 'v1/keys'

    @lru_cache(maxsize=1)
    def get_all_lido_keys(self, blockstamp: BlockStamp) -> List[LidoKey]:
        """
        Returns keys if blockstamp < blockNumber from response
        """
        for i in range(self.RETRY_COUNT):
            data, meta = self._get(self.ALL_KEYS)
            if meta['elBlockSnapshot']['blockNumber'] >= blockstamp['block_number']:
                return data

            # Don't sleep in last cycle
            if i != self.RETRY_COUNT - 1:
                sleep(self.SLEEP_SECONDS)

        raise KeysOutdatedException(f'API KEY Service stucked, no updates for {self.SLEEP_SECONDS * self.RETRY_COUNT} seconds.')
