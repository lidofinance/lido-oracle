from typing import Any, Optional
from abc import abstractmethod, ABC


class InconsistentProviders(Exception):
    pass


class NotHealthyProvider(Exception):
    pass


class ProviderConsistencyModule(ABC):
    """
    A class that provides HTTP provider ability to check that
    provided hosts are alive and chain ids are same.

    Methods must be implemented:
    def get_all_providers(self) -> [any]:
    def _get_chain_id_with_provider(self, int) -> int:
    """
    def check_providers_consistency(self) -> Optional[int]:
        chain_id = None

        for provider_index in range(len(self.get_all_providers())):
            try:
                curr_chain_id = self._get_chain_id_with_provider(provider_index)
            except Exception as error:
                raise NotHealthyProvider(f'Provider [{provider_index}] does not responding.') from error

            if chain_id is None:
                chain_id = curr_chain_id
            elif chain_id != curr_chain_id:
                raise InconsistentProviders(f'Different chain ids detected for {provider_index=}. '
                                            f'Expected {curr_chain_id=}, got {chain_id=}.')

        return chain_id

    @abstractmethod
    def get_all_providers(self) -> list[Any]:
        """Returns list of hosts or providers."""
        raise NotImplementedError("get_all_providers should be implemented")

    @abstractmethod
    def _get_chain_id_with_provider(self, provider_index: int) -> int:
        """Does a health check call and returns chain_id for current host"""
        raise NotImplementedError("get_chain_id should be implemented")
