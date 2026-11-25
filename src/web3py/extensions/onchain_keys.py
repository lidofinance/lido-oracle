import logging
from typing import TYPE_CHECKING, cast

from web3 import Web3 as _Web3
from web3.module import Module

from src import variables
from src.providers.keys.client import KAPIInconsistentData, ModuleOperatorsKeys
from src.providers.keys.onchain import OnchainKeysConfig, OnchainKeysFetcher
from src.providers.keys.types import LidoKey
from src.types import BlockStamp, StakingModuleAddress
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.fingerprint import log_fingerprint


if TYPE_CHECKING:
    from src.web3py.types import Web3  # pragma: no cover


logger = logging.getLogger(__name__)


class OnchainKeysModule(Module):
    """
    Drop-in replacement of Keys API (`w3.kac`) that reads used keys from the staking module contracts
    through the execution client. Enabled with KEYS_SOURCE=onchain.
    """

    w3: Web3

    def __init__(self, w3: _Web3, config: OnchainKeysConfig | None = None):
        super().__init__(w3)
        self.fetcher = OnchainKeysFetcher(
            w3,
            config
            or OnchainKeysConfig(
                workers=variables.ONCHAIN_KEYS_WORKERS,
                use_multicall=variables.ONCHAIN_KEYS_USE_MULTICALL,
                call_gas_limit=variables.ONCHAIN_KEYS_CALL_GAS_LIMIT,
                call_return_bytes_limit=variables.ONCHAIN_KEYS_CALL_RETURN_BYTES_LIMIT,
                multicall_address=_Web3.to_checksum_address(variables.MULTICALL3_ADDRESS),
            ),
        )

    @lru_cache(maxsize=1)
    def get_used_lido_keys(self, blockstamp: BlockStamp) -> list[LidoKey]:
        """Used keys of all staking modules registered in StakingRouter."""
        modules = self.w3.lido_contracts.staking_router.get_staking_modules(blockstamp.block_hash)
        modules_keys = self.fetcher.fetch_modules_keys(
            [module.staking_module_address for module in modules],
            blockstamp.block_hash,
        )

        keys = [key for module_keys in modules_keys for key in module_keys.keys]
        self._check_no_duplicates(keys)
        log_fingerprint(logger, 'Onchain used keys', keys)
        return keys

    @lru_cache(maxsize=1)
    def get_used_module_operators_keys(
        self, module_address: StakingModuleAddress, blockstamp: BlockStamp
    ) -> ModuleOperatorsKeys:
        """Same shape as Keys API `v1/modules/{module}/operators/keys?used=true`, as far as the oracle reads it."""
        (module_keys,) = self.fetcher.fetch_modules_keys([module_address], blockstamp.block_hash)

        data = ModuleOperatorsKeys(
            keys=module_keys.keys,
            module={'stakingModuleAddress': module_address},
            operators=[
                {'index': operator_id, 'moduleAddress': module_address, 'usedSigningKeys': deposited}
                for operator_id, deposited in sorted(module_keys.deposited_keys.items())
            ],
        )
        log_fingerprint(logger, 'Onchain module operators keys', cast(dict, data), module=module_address)
        return data

    @staticmethod
    def _check_no_duplicates(keys: list[LidoKey]) -> None:
        keys_seen: dict[str, LidoKey] = {}
        for key in keys:
            if key.key in keys_seen:
                raise KAPIInconsistentData(f"Got duplicated key={key}, previously found={keys_seen[key.key]}")
            keys_seen[key.key] = key
