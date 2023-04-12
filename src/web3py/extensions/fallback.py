from typing import Any, Tuple, List

from web3_multi_provider import FallbackProvider
from src.web3py.extensions.consistency import ProviderConsistencyModule
from web3 import Web3


class FallbackProviderModule(ProviderConsistencyModule, FallbackProvider):

    def get_all_hosts(self) -> List[Tuple[Any, str]]:
        return list(map(lambda provider: (provider, provider.endpoint_uri), self._providers))

    def get_chain_id(self, host) -> int:
        return Web3.to_int(hexstr=host.make_request("eth_chainId", []).get('result'))
