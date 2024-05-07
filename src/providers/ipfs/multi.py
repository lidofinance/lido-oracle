from typing import Any, Iterable, Sequence
import logging

from .types import IPFSError, IPFSProvider


logger = logging.getLogger(__name__)


class MultiIPFSProvider:
    """Fallback-driven provider for IPFS"""

    providers: Sequence[IPFSProvider]

    _current_provider_index: int = 0
    _last_working_provider_index: int = 0

    def __init__(self, providers: Iterable[IPFSProvider]) -> None:
        super().__init__()
        self.providers = []
        for p in providers:
            assert isinstance(p, IPFSProvider)
            self.providers.append(p)

    def __getattribute__(self, name: str, /) -> Any:
        if name in ("fetch", "upload", "pin"):
            return self._retry_call(name)
        return super().__getattribute__(name)

    def _retry_call(self, name: str):
        def wrapper(*args, **kwargs):
            try:
                provider = self.providers[self._current_provider_index]
                fn = getattr(provider, name)
                result = fn(*args, **kwargs)
            except IPFSError:
                self._current_provider_index = (self._current_provider_index + 1) % len(self.providers)
                if self._last_working_provider_index == self._current_provider_index:
                    logger.error({"msg": "No more IPFS providers left to call"})
                    raise
                return wrapper(*args, **kwargs)

            self._last_working_provider_index = self._current_provider_index
            return result

        return wrapper
