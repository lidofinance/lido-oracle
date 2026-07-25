import logging
from time import sleep
from typing import TypedDict, cast

from src.metrics.prometheus.basic import KEYS_API_LATEST_BLOCKNUMBER, KEYS_API_REQUESTS_DURATION
from src.providers.http_provider import HTTPProvider, NotOkResponse, data_is_dict
from src.providers.keys.types import KeysApiStatus, LidoKey
from src.types import BlockStamp, StakingModuleAddress
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.fingerprint import log_fingerprint_hex


logger = logging.getLogger(__name__)


class KeysOutdatedException(Exception):
    pass


class KAPIClientError(NotOkResponse):
    pass


class KAPIInconsistentData(Exception):
    pass


class ElBlockSnapshot(TypedDict):
    """`meta.elBlockSnapshot` — the Keys API's own view of where its data comes from.

    `lastChangedBlockHash` is the block at which any watched contract last changed; two
    instances reporting the same value have consumed the same on-chain key updates.
    """

    blockNumber: int
    blockHash: str
    timestamp: int
    lastChangedBlockHash: str


class KAPIModule(TypedDict):
    id: int
    stakingModuleAddress: str


class ModuleOperatorsKeys(TypedDict):
    keys: list[LidoKey]
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

    def _get_with_blockstamp(
        self, url: str, blockstamp: BlockStamp, params: dict | None = None
    ) -> tuple[dict | list, ElBlockSnapshot]:
        """
        Returns (response, snapshot) if blockstamp < blockNumber from response
        """
        for i in range(self.retry_count):
            data, meta = self._get(url, query_params=params)
            snapshot = cast(ElBlockSnapshot, meta['meta']['elBlockSnapshot'])
            blocknumber_meta = snapshot['blockNumber']
            KEYS_API_LATEST_BLOCKNUMBER.set(blocknumber_meta)
            # The snapshot pins which on-chain state this answer was built from. Members
            # comparing reports need it to tell a Keys API disagreement (different
            # snapshot, or same snapshot and different keys) from anything else.
            logger.info(
                {
                    'msg': 'Keys API response snapshot.',
                    'endpoint': url,
                    'attempt': i + 1,
                    'requested_block_number': blockstamp.block_number,
                    'el_block_snapshot': snapshot,
                }
            )
            if blocknumber_meta >= blockstamp.block_number:
                return data, snapshot

            if i != self.retry_count - 1:
                sleep(self.backoff_factor)

        raise KeysOutdatedException(
            f'Keys API Service stuck, no updates for {self.backoff_factor * self.retry_count} seconds.'
        )

    def get_used_lido_keys(self, blockstamp: BlockStamp) -> list[LidoKey]:
        """Docs: https://keys-api.lido.fi/api/static/index.html#/keys/KeysController_get"""
        keys, _ = self._get_used_lido_keys_with_snapshot(blockstamp)
        return keys

    def get_used_lido_keys_snapshot(self, blockstamp: BlockStamp) -> ElBlockSnapshot:
        """The `elBlockSnapshot` the used-key set was served at. Cached alongside the keys."""
        _, snapshot = self._get_used_lido_keys_with_snapshot(blockstamp)
        return snapshot

    @lru_cache(maxsize=1)
    def _get_used_lido_keys_with_snapshot(self, blockstamp: BlockStamp) -> tuple[list[LidoKey], ElBlockSnapshot]:
        response, snapshot = self._get_with_blockstamp(self.USED_KEYS, blockstamp)
        data = [LidoKey.from_response(**x) for x in cast(list, response)]
        self._check_used_keys(data)
        self._log_keys_fingerprint(data, snapshot)
        return data, snapshot

    @staticmethod
    def _log_keys_fingerprint(keys: list[LidoKey], snapshot: ElBlockSnapshot) -> None:
        """Fingerprint the used-key set so two members can diff it from their logs alone.

        The set is ~485k pubkeys / ~47 MB, gone the moment the Keys API moves on, and no
        operator wants to trade it around. `xor` alone identifies the odd key out when the
        sets differ by exactly one — the shape every pending-balance split has taken so far.
        """
        by_module: dict[str, int] = {}
        for key in keys:
            module = str(key.module_address).lower()
            by_module[module] = by_module.get(module, 0) + 1

        log_fingerprint_hex(
            logger,
            'Used Lido keys',
            (key.key for key in keys),
            by_module=by_module,
            el_block_number=snapshot.get('blockNumber'),
            last_changed_block_hash=snapshot.get('lastChangedBlockHash'),
        )

    @lru_cache(maxsize=1)
    def get_used_module_operators_keys(
        self, module_address: StakingModuleAddress, blockstamp: BlockStamp
    ) -> ModuleOperatorsKeys:
        """
        Docs: https://keys-api.lido.fi/api/static/index.html#/operators-keys/SRModulesOperatorsKeysController_getOperatorsKeys
        """
        response, snapshot = self._get_with_blockstamp(
            self.USED_MODULE_OPERATORS_KEYS.format(module_address), blockstamp
        )
        data = cast(dict, response)
        if (kapi_module_address := data['module']['stakingModuleAddress']) != module_address:
            raise KAPIInconsistentData(f"Module address mismatch: {kapi_module_address=} != {module_address=}")

        data['keys'] = [LidoKey.from_response(**k) for k in data['keys']]
        self._check_used_keys(data['keys'])
        self._log_used_signing_keys_consistency(module_address, data, snapshot)

        return cast(ModuleOperatorsKeys, data)

    @staticmethod
    def _log_used_signing_keys_consistency(module_address: str, data: dict, snapshot: ElBlockSnapshot) -> None:
        """Check a Keys API instance against itself, per operator.

        `used` is a flag on each key row; `usedSigningKeys` is a counter on the operator
        row, maintained independently. For every operator the two must agree. A shortfall
        means the instance knows the operator deposited N keys but has only flagged N-1 of
        them used — that key is invisible to the oracle and its queued deposit is missing
        from the pending balance. This needs nothing but the response already in hand, so
        it names a short instance without waiting for members to compare hashes.
        """
        used_rows: dict[int, int] = {}
        for key in data['keys']:
            used_rows[key.operator_index] = used_rows.get(key.operator_index, 0) + 1

        try:
            mismatches = [
                {
                    'operator_index': operator['index'],
                    'used_signing_keys': operator['usedSigningKeys'],
                    'used_key_rows': used_rows.get(operator['index'], 0),
                    'delta': used_rows.get(operator['index'], 0) - operator['usedSigningKeys'],
                }
                for operator in data['operators']
                if used_rows.get(operator['index'], 0) != operator['usedSigningKeys']
            ]
        except (KeyError, TypeError) as error:
            logger.warning({'msg': 'Keys API used-key self-consistency skipped.', 'error': repr(error)})
            return

        log = logger.warning if mismatches else logger.info
        log(
            {
                'msg': 'Keys API used-key self-consistency.',
                'module_address': module_address,
                'operators': len(data['operators']),
                'used_keys': len(data['keys']),
                'mismatches': mismatches,
                'el_block_number': snapshot.get('blockNumber'),
            }
        )

    def get_status(self) -> KeysApiStatus:
        """Docs: https://keys-api.lido.fi/api/static/index.html#/status/StatusController_get"""
        data, _ = self._get(self.STATUS, validate_response=data_is_dict)
        return KeysApiStatus.from_response(**data)

    def _get_chain_id_with_provider(self, provider_index: int) -> int:
        data, _ = self._get_without_fallbacks(self.hosts[provider_index], self.STATUS, validate_response=data_is_dict)
        return KeysApiStatus.from_response(**data).chain_id

    def _check_used_keys(self, keys: list[LidoKey]):
        keys_seen: dict[str, LidoKey] = {}
        for k in keys:
            if not k.used:
                raise KAPIInconsistentData(f"Got unused key={k}")
            if k.key in keys_seen:
                raise KAPIInconsistentData(f"Got duplicated key={k}, previously found={keys_seen[k.key]}")
            keys_seen[k.key] = k
