import logging
import requests

from .types import FetchError, IPFSProvider, PinError, UploadError
from .cid import CIDv0, CIDv1


logger = logging.getLogger(__name__)


class PublicIPFS(IPFSProvider):
    """Public IPFS gateway (fetch-only provider)"""

    GATEWAY = "https://ipfs.io"

    def __init__(self, *, timeout: int) -> None:
        super().__init__()
        self.timeout = timeout

    def fetch(self, cid: CIDv0 | CIDv1) -> bytes:
        url = f"{self.GATEWAY}/ipfs/{cid}"
        try:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as ex:
            logger.error({"msg": "Request has been failed", "error": str(ex)})
            raise FetchError(cid) from ex
        return resp.content

    def upload(self, content: bytes, name: str | None = None) -> CIDv0 | CIDv1:
        raise UploadError

    def pin(self, cid: CIDv0 | CIDv1) -> None:
        raise PinError(cid)
