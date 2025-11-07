from abc import ABC, abstractmethod

import multiformats

from src.utils.car import CARConverter
from src import variables
from .cid import CID, CIDv0


class IPFSError(Exception):
    """Base class for IPFS provider errors"""


class FetchError(IPFSError):
    """Raised if no content found for the given CID"""

    cid: CID

    def __init__(self, cid: CID) -> None:
        super().__init__(self)
        self.cid = cid

    def __str__(self) -> str:
        base_msg = f"Unable to fetch {repr(self.cid)}"
        if self.__cause__ is not None:
            return f"{base_msg}: {self.__cause__}"
        return base_msg


class UploadError(IPFSError):
    def __str__(self) -> str:
        if self.args:
            return super().__str__()
        if self.__cause__ is not None:
            return str(self.__cause__)
        return super().__str__()


class CIDValidationError(IPFSError):
    def __init__(self, expected_cid: str, actual_cid: str):
        self.expected_cid = expected_cid
        self.actual_cid = actual_cid
        super().__init__(f"CID validation failed: expected {expected_cid} but got {actual_cid}")


class PinError(IPFSError):
    cid: CID

    def __init__(self, cid: CID) -> None:
        super().__init__(self)
        self.cid = cid

    def __str__(self) -> str:
        return f"Unable to pin {repr(self.cid)}"


class IPFSProvider(ABC):
    """Interface for all implementations of an [IPFS](https://docs.ipfs.tech) provider"""

    def __init__(self) -> None:
        self.car_converter = CARConverter()

    def _normalize_cid(self, cid: str) -> CID:
        parsed_cid = multiformats.CID.decode(cid)
        if parsed_cid.version == 1:
            parsed_cid = parsed_cid.set(version=0, base='base58btc')
        return CID(str(parsed_cid))

    def fetch(self, cid: CID) -> bytes:
        content = self._fetch(cid)
        if variables.IPFS_VALIDATE_CID:
            normalized_cid = self._normalize_cid(str(cid))
            self._validate_cid(normalized_cid, content)
        return content

    @abstractmethod
    def _fetch(self, cid: CID) -> bytes:
        pass

    def publish(self, content: bytes, name: str | None = None) -> CID:
        cid = self.upload(content, name)

        if variables.IPFS_VALIDATE_CID:
            self._validate_cid(cid, content)

        self.pin(cid)
        return cid

    @abstractmethod
    def _upload(self, content: bytes, name: str | None = None) -> str:
        pass

    def upload(self, content: bytes, name: str | None = None) -> CIDv0:
        cid_str = self._upload(content, name)
        normalized_cid = self._normalize_cid(cid_str)
        return CIDv0(str(normalized_cid))

    @abstractmethod
    def pin(self, cid: CID) -> None:
        """Pin the content, see https://docs.ipfs.tech/how-to/pin-files"""

    def _validate_cid(self, cid: CID, content: bytes) -> None:
        """Validate that the CID correctly represents the content hash.

        Args:
            cid: Content identifier to validate
            content: Original content bytes

        Raises:
            CIDValidationError: If CID doesn't match the content
        """
        proof_cid = self.car_converter.create_unixfs_based_cid(content)

        if proof_cid != str(cid):
            raise CIDValidationError(proof_cid, str(cid))
