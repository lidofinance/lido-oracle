from abc import ABC
from functools import lru_cache

from src.modules.submodules.provider import ProviderModule
from src.typings import BlockStamp


class LidoKeys(ProviderModule, ABC):
    @lru_cache(maxsize=1)
    def get_lido_keys(self, blockstamp: BlockStamp):
        pass

    @lru_cache(maxsize=1)
    def get_lido_validators(self, blockstamp: BlockStamp):
        pass

    @lru_cache(maxsize=1)
    def get_lido_node_operators(self, blockstamp: BlockStamp):
        pass
