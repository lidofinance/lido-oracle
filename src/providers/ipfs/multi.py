import logging
from abc import ABC
from functools import wraps
from typing import Generic, Iterable, TypeVar

from .cid import CIDv0, CIDv1
from .types import IPFSError, IPFSProvider

logger = logging.getLogger(__name__)


T = TypeVar("T")


class MultiProvider(Generic[T], ABC):
    """Base class for working with multiple providers"""

    providers: list[T]
    current_provider_index: int = 0
    last_working_provider_index: int = 0

    @property
    def provider(self) -> T:
        return self.providers[self.current_provider_index]


def with_fallback(fn):
    @wraps(fn)
    def wrapped(self: MultiProvider, *args, **kwargs):
        try:
            result = fn(self, *args, **kwargs)
        except IPFSError:
            self.current_provider_index = (self.current_provider_index + 1) % len(self.providers)
            if self.last_working_provider_index == self.current_provider_index:
                logger.error({"msg": "No more IPFS providers left to call"})
                raise
            return wrapped(self, *args, **kwargs)

        self.last_working_provider_index = self.current_provider_index
        return result

    return wrapped


class MultiIPFSProvider(IPFSProvider, MultiProvider[IPFSProvider]):
    """Fallback-driven provider for IPFS"""

    def __init__(self, providers: Iterable[IPFSProvider]) -> None:
        super().__init__()
        self.providers = list(providers)
        assert self.providers
        for p in self.providers:
            assert isinstance(p, IPFSProvider)

    @with_fallback
    def upload(self, content: bytes, name: str | None = None) -> CIDv0 | CIDv1:
        return self.provider.upload(content, name)

    @with_fallback
    def fetch(self, cid: CIDv0 | CIDv1) -> bytes:
        return self.provider.fetch(cid)

    @with_fallback
    def pin(self, cid: CIDv0 | CIDv1) -> None:
        self.provider.pin(cid)
