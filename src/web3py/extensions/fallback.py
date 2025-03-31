from typing import Any

from web3 import Web3
from web3.types import RPCEndpoint
from web3_multi_provider import FallbackProvider

from src.providers.consistency import ProviderConsistencyModule


class FallbackProviderModule(ProviderConsistencyModule, FallbackProvider):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_all_providers(self) -> list[Any]:
        return self._providers  # type: ignore[attr-defined]

    def _get_chain_id_with_provider(self, provider_index: int) -> int:
        response_chain_id = self._providers[provider_index].make_request(RPCEndpoint("eth_chainId"), [])  # type: ignore[attr-defined]
        return Web3.to_int(hexstr=response_chain_id.get('result'))
