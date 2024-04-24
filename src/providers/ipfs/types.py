from abc import ABC, abstractmethod
from typing import NewType


CIDv0 = NewType("CIDv0", str)
CIDv1 = NewType("CIDv1", str)


class NotFound(Exception):
    """Raised if no content found for the given CID"""


class IPFSProvider(ABC):
    """Interface for all implementations of an [IPFS](https://docs.ipfs.tech) provider"""

    @abstractmethod
    def fetch(self, cid: CIDv0 | CIDv1) -> bytes: ...

    @abstractmethod
    def upload(self, content: bytes, name: str | None = None) -> CIDv0 | CIDv1: ...

    @abstractmethod
    def pin(self, cid: CIDv0 | CIDv1) -> None:
        """Pin the content, see https://docs.ipfs.tech/how-to/pin-files"""
