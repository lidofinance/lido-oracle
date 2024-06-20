import logging
from functools import wraps
from typing import Iterable

from .cid import CIDv0, CIDv1
from .types import IPFSError, IPFSProvider

logger = logging.getLogger(__name__)


class MaxRetryError(IPFSError):
    ...


class MultiIPFSProvider(IPFSProvider):
    """Fallback-driven provider for IPFS"""

    # NOTE: The provider is NOT thread-safe.

    providers: list[IPFSProvider]
    current_provider_index: int = 0
    last_working_provider_index: int = 0

    def __init__(self, providers: Iterable[IPFSProvider], *, retries: int = 3) -> None:
        super().__init__()
        self.retries = retries
        self.providers = list(providers)
        assert self.providers
        for p in self.providers:
            assert isinstance(p, IPFSProvider)

    @staticmethod
    def with_fallback(fn):
        @wraps(fn)
        def wrapped(self: "MultiIPFSProvider", *args, **kwargs):
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

    @staticmethod
    def retry(fn):
        @wraps(fn)
        def wrapped(self: "MultiIPFSProvider", *args, **kwargs):
            retries_left = self.retries
            while retries_left:
                try:
                    return fn(self, *args, **kwargs)
                except IPFSError as ex:
                    retries_left -= 1
                    if not retries_left:
                        raise MaxRetryError from ex
                    logger.warning(
                        {"msg": f"Retrying a failed call of {fn.__name__}, {retries_left=}", "error": str(ex)}
                    )
            raise MaxRetryError

        return wrapped

    @property
    def provider(self) -> IPFSProvider:
        return self.providers[self.current_provider_index]

    @with_fallback
    @retry
    def fetch(self, cid: CIDv0 | CIDv1) -> bytes:
        return self.provider.fetch(cid)

    @with_fallback
    @retry
    def publish(self, content: bytes, name: str | None = None) -> CIDv0 | CIDv1:
        # If the current provider fails to upload or pin a file, it makes sense
        # to try to both upload and to pin via a different provider.
        return self.provider.publish(content, name)

    def upload(self, content: bytes, name: str | None = None) -> CIDv0 | CIDv1:
        # It doesn't make sense to upload a file to a different providers networks
        # without a guarantee the file will be available via another one.
        raise NotImplementedError

    def pin(self, cid: CIDv0 | CIDv1) -> None:
        # CID can be unavailable for the next provider in the providers list.
        raise NotImplementedError
