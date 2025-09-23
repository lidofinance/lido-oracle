from time import sleep
from typing import List, TypedDict, cast

from src.metrics.prometheus.basic import KEYS_API_LATEST_BLOCKNUMBER, KEYS_API_REQUESTS_DURATION
from src.providers.http_provider import HTTPProvider, NotOkResponse, data_is_dict
from src.providers.keys.types import KeysApiStatus, LidoKey
from src.types import BlockStamp, StakingModuleAddress
from src.utils.cache import global_lru_cache as lru_cache


class KeysOutdatedException(Exception):
    pass


class KAPIClientError(NotOkResponse):
    pass


class KAPIInconsistentData(Exception):
    pass


class KAPIModule(TypedDict):
    id: int
    stakingModuleAddress: str


class ModuleOperatorsKeys(TypedDict):
    keys: List[LidoKey]
    module: KAPIModule
    operators: list


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
    PROVIDER_EXCEPTION = KAPIClientError

    USED_MODULE_OPERATORS_KEYS = 'v1/modules/{}/operators/keys?used=true'
    USED_KEYS = 'v1/keys?used=true'
    STATUS = 'v1/status'

    def _get_with_blockstamp(self, url: str, blockstamp: BlockStamp, params: dict | None = None) -> dict | list:
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

        raise KeysOutdatedException(
            f'Keys API Service stuck, no updates for {self.backoff_factor * self.retry_count} seconds.'
        )

    @lru_cache(maxsize=1)
    def get_used_lido_keys(self, blockstamp: BlockStamp) -> list[LidoKey]:
        """Docs: https://keys-api.lido.fi/api/static/index.html#/keys/KeysController_get"""
        data = [LidoKey.from_response(**x) for x in self._get_with_blockstamp(self.USED_KEYS, blockstamp)]
        self._check_used_keys(data)
        return data

    @lru_cache(maxsize=1)
    def get_used_module_operators_keys(
        self, module_address: StakingModuleAddress, blockstamp: BlockStamp
    ) -> ModuleOperatorsKeys:
        """
        Docs: https://keys-api.lido.fi/api/static/index.html#/operators-keys/SRModulesOperatorsKeysController_getOperatorsKeys
        """
        data = cast(dict, self._get_with_blockstamp(self.USED_MODULE_OPERATORS_KEYS.format(module_address), blockstamp))
        if (kapi_module_address := data['module']['stakingModuleAddress']) != module_address:
            raise KAPIInconsistentData(f"Module address mismatch: {kapi_module_address=} != {module_address=}")

        data['keys'] = [LidoKey.from_response(**k) for k in data['keys']]
        self._check_used_keys(data['keys'])

        return cast(ModuleOperatorsKeys, data)

    def get_status(self) -> KeysApiStatus:
        """Docs: https://keys-api.lido.fi/api/static/index.html#/status/StatusController_get"""
        data, _ = self._get(self.STATUS, retval_validator=data_is_dict)
        return KeysApiStatus.from_response(**data)

    def _get_chain_id_with_provider(self, provider_index: int) -> int:
        data, _ = self._get_without_fallbacks(self.hosts[provider_index], self.STATUS, retval_validator=data_is_dict)
        return KeysApiStatus.from_response(**data).chainId

    def _check_used_keys(self, keys: list[LidoKey]):
        keys_seen: dict[str, LidoKey] = {}
        for k in keys:
            if not k.used:
                raise KAPIInconsistentData(f"Got unused key={k}")
            if k.key in keys_seen:
                raise KAPIInconsistentData(f"Got duplicated key={k}, previously found={keys_seen[k.key]}")
            keys_seen[k.key] = k
