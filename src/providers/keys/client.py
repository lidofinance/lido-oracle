from time import sleep
from typing import Optional, cast

from src.metrics.prometheus.basic import KEYS_API_REQUESTS_DURATION, KEYS_API_LATEST_BLOCKNUMBER
from src.providers.http_provider import HTTPProvider
from src.providers.keys.typings import LidoKey, KeysApiStatus
from src.typings import BlockStamp
from src.utils.dataclass import list_of_dataclasses
from src.utils.cache import global_lru_cache as lru_cache


class KeysOutdatedException(Exception):
    pass


class KeysAPIClient(HTTPProvider):
    """
    Lido Keys are stored in different modules in on-chain and off-chain format.
    Keys API service fetches all lido keys and provide them in convenient format.
    Keys could not be deleted, so the amount of them always increasing.
    One thing to check before use data from Keys API service is that latest fetched block in meta field is greater
    than the block we are fetching on.

    Keys API specification can be found here https://keys-api.lido.fi/api/static/index.html
    """
    PROMETHEUS_HISTOGRAM = KEYS_API_REQUESTS_DURATION

    USED_KEYS = 'v1/keys?used=true'
    STATUS = 'v1/status'

    def _get_with_blockstamp(self, url: str, blockstamp: BlockStamp, params: Optional[dict] = None) -> dict | list:
        """
        Returns response if blockstamp < blockNumber from response
        """
        for i in range(self.retry_count):
            data, meta = self._get(url, query_params=params)
            blocknumber_meta = meta['meta']['elBlockSnapshot']['blockNumber']
            KEYS_API_LATEST_BLOCKNUMBER.set(blocknumber_meta)
            if blocknumber_meta >= blockstamp.block_number:
                return data

            if i != self.retry_count - 1:
                sleep(self.backoff_factor)

        raise KeysOutdatedException(f'Keys API Service stuck, no updates for {self.backoff_factor * self.retry_count} seconds.')

    @lru_cache(maxsize=1)
    @list_of_dataclasses(LidoKey.from_response)
    def get_used_lido_keys(self, blockstamp: BlockStamp) -> list[dict]:
        """Docs: https://keys-api.lido.fi/api/static/index.html#/keys/KeysController_get"""
        return cast(list[dict], self._get_with_blockstamp(self.USED_KEYS, blockstamp))

    def get_status(self) -> KeysApiStatus:
        """Docs: https://keys-api.lido.fi/api/static/index.html#/status/StatusController_get"""
        data, _ = self._get(self.STATUS)
        return KeysApiStatus.from_response(**cast(dict, data))

    def _get_chain_id_with_provider(self, provider_index: int) -> int:
        data, _ = self._get_without_fallbacks(self.hosts[provider_index], self.STATUS)
        return KeysApiStatus.from_response(**cast(dict, data)).chainId
