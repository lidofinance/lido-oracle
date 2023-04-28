from typing import Any

from web3_multi_provider import FallbackProvider
from src.providers.consistency import ProviderConsistencyModule
from web3 import Web3


class FallbackProviderModule(ProviderConsistencyModule, FallbackProvider):
    def get_all_providers(self) -> list[Any]:
        return self._providers  # type: ignore[attr-defined]

    def _get_chain_id_with_provider(self, provider_index: int) -> int:
        return Web3.to_int(hexstr=self._providers[provider_index].make_request("eth_chainId", []).get('result'))  # type: ignore[attr-defined]
