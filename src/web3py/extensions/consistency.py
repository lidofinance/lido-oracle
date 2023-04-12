from typing import Any, Tuple, List, Optional
from abc import abstractmethod, ABC
from requests.exceptions import ConnectionError as RequestsConnectionError


class ProviderConsistencyModule(ABC):
    """
    A class that provides HTTP provider with the ability to check that
    provided hosts are alive and chain ids are same.

    Methods must be implemented:
    def get_all_hosts(self) -> [any, str]:
    def get_chain_id(self, host) -> int:
    """
    def check_providers_consistency(self) -> Optional[int]:
        chain_id = None

        for (host, endpoint) in self.get_all_hosts():
            try:
                curr_chain_id = self.get_chain_id(host)
                if chain_id is None:
                    chain_id = curr_chain_id
                elif chain_id != curr_chain_id:
                    raise ValueError(f'Different chain ids detected: {endpoint}')
            except Exception as exc:
                raise RequestsConnectionError(f"Provider doesn't respond: {endpoint}") from exc

        return chain_id

    @abstractmethod
    def get_all_hosts(self) -> List[Tuple[Any, str]]:
        """
        Returns a list of hosts and URIs to be health checked.

        HTTP provider returns URI string.
        Web3 provider returns Provider instance.
        """
        raise NotImplementedError("get_all_hosts should be implemented")

    @abstractmethod
    def get_chain_id(self, host) -> int:
        """Does a health check call and returns chain_id for current host"""
        raise NotImplementedError("_chain_id should be implemented")
