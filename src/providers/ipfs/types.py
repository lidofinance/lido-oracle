from abc import ABC, abstractmethod

from .cid import CID


class IPFSError(Exception):
    """Base class for IPFS provider errors"""


class FetchError(IPFSError):
    """Raised if no content found for the given CID"""

    cid: CID

    def __init__(self, cid: CID) -> None:
        super().__init__(self)
        self.cid = cid

    def __str__(self) -> str:
        return f"Unable to fetch {repr(self.cid)}"


class UploadError(IPFSError): ...


class PinError(IPFSError):
    cid: CID

    def __init__(self, cid: CID) -> None:
        super().__init__(self)
        self.cid = cid

    def __str__(self) -> str:
        return f"Unable to pin {repr(self.cid)}"


class IPFSProvider(ABC):
    """Interface for all implementations of an [IPFS](https://docs.ipfs.tech) provider"""

    @abstractmethod
    def fetch(self, cid: CID) -> bytes: ...

    def publish(self, content: bytes, name: str | None = None) -> CID:
        cid = self.upload(content, name)
        self.pin(cid)
        return cid

    @abstractmethod
    def upload(self, content: bytes, name: str | None = None) -> CID: ...

    @abstractmethod
    def pin(self, cid: CID) -> None:
        """Pin the content, see https://docs.ipfs.tech/how-to/pin-files"""
