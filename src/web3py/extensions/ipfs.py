import logging
from functools import wraps
from typing import Iterable
from web3 import Web3
from web3.module import Module

from src.providers.ipfs.cid import CID
from src.providers.ipfs.types import IPFSError, IPFSProvider
from src.types import FrameNumber

logger = logging.getLogger(__name__)


class MaxRetryError(IPFSError):
    pass


class NoMoreProvidersError(IPFSError):
    pass


class IPFS(Module):
    """IPFS web3 module with multi-provider fallback support"""

    w3: Web3

    def __init__(self, w3: Web3, providers: Iterable[IPFSProvider], *, retries: int = 3) -> None:
        super().__init__(w3)
        self.retries = retries
        self.providers = list(providers)
        self.current_provider_index: int = 0
        self.last_working_provider_index: int = 0
        self.current_frame: FrameNumber | None = None

        assert self.providers

        for p in self.providers:
            assert isinstance(p, IPFSProvider)

    @staticmethod
    def with_fallback(fn):
        @wraps(fn)
        def wrapped(self: "IPFS", *args, **kwargs):
            try:
                result = fn(self, *args, **kwargs)
            except Exception as ex:  # pylint: disable=broad-exception-caught
                self.current_provider_index = (self.current_provider_index + 1) % len(self.providers)
                if self.last_working_provider_index == self.current_provider_index:
                    logger.error({"msg": "No more IPFS providers left to call"})
                    raise NoMoreProvidersError from ex
                return wrapped(self, *args, **kwargs)

            self.last_working_provider_index = self.current_provider_index
            return result

        return wrapped

    @staticmethod
    def retry(fn):
        @wraps(fn)
        def wrapped(self: "IPFS", *args, **kwargs):
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

    def _set_provider_for_frame(self, provider_rotation_frame: FrameNumber) -> None:
        # Preserve the fallback state within the same frame if occurred
        if self.current_frame != provider_rotation_frame:
            self.current_frame = provider_rotation_frame
            self.current_provider_index = provider_rotation_frame % len(self.providers)
            self.last_working_provider_index = self.current_provider_index

    @with_fallback
    @retry
    def fetch(self, cid: CID, provider_rotation_frame: FrameNumber) -> bytes:
        self._set_provider_for_frame(provider_rotation_frame)
        logger.info({
            "msg": "Called: w3.ipfs.fetch(...)",
            "provider_rotation_frame": provider_rotation_frame,
            "provider_index": self.current_provider_index,
            "provider_class": self.provider.__class__.__name__,
            "cid": str(cid)
        })
        return self.provider.fetch(cid)

    @with_fallback
    @retry
    def publish(self, content: bytes, provider_rotation_frame: FrameNumber, name: str | None = None) -> CID:
        self._set_provider_for_frame(provider_rotation_frame)
        logger.info({
            "msg": "Called: w3.ipfs.publish(...)",
            "provider_rotation_frame": provider_rotation_frame,
            "provider_index": self.current_provider_index,
            "provider_class": self.provider.__class__.__name__
        })
        return self.provider.publish(content, name)
