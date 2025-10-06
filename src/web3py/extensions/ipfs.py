import logging
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
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

        self.current_provider_index: int = 0
        self.last_working_provider_index: int = 0
        self.current_frame: FrameNumber | None = None

        self.providers = list(providers)
        # Randomize provider order to reduce probability that
        # all oracles use the same provider simultaneously in one frame
        random.shuffle(self.providers)

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

    @retry
    def _upload_to_provider(self, provider: IPFSProvider, content: bytes, name: str | None = None) -> CID:
        return provider.publish(content, name)

    def publish(self, content: bytes, name: str | None = None) -> CID:
        logger.info({
            "msg": "Started: w3.ipfs.publish(...)",
            "total_providers": len(self.providers)
        })

        successful_uploads = []
        failed_uploads = []

        with ThreadPoolExecutor(max_workers=len(self.providers)) as executor:
            future_to_provider = {
                executor.submit(self._upload_to_provider, provider, content, name): provider
                for provider in self.providers
            }

            for future in as_completed(future_to_provider):
                provider = future_to_provider[future]
                try:
                    cid = future.result()
                    successful_uploads.append({
                        "provider_class": provider.__class__.__name__,
                        "cid": str(cid)
                    })
                except Exception as ex:  # pylint: disable=broad-exception-caught
                    failed_uploads.append({
                        "provider_class": provider.__class__.__name__,
                        "error": str(ex)
                    })

        if not successful_uploads:
            logger.error({
                "msg": "Failed to upload to all providers",
                "failed_uploads": failed_uploads
            })
            raise NoMoreProvidersError("All providers failed during upload")

        logger.info({
            "msg": "Completed: w3.ipfs.publish(...)",
            "successful_uploads": successful_uploads,
            "failed_uploads": failed_uploads,
        })

        return CID(successful_uploads[0]["cid"])
