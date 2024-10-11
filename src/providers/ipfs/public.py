import logging

import requests

from .cid import CID
from .types import FetchError, IPFSProvider, PinError, UploadError

logger = logging.getLogger(__name__)


class PublicIPFS(IPFSProvider):
    """Public IPFS gateway (fetch-only provider)"""

    # pylint:disable=duplicate-code

    GATEWAY = "https://ipfs.io"

    def __init__(self, *, timeout: int) -> None:
        super().__init__()
        self.timeout = timeout

    def fetch(self, cid: CID) -> bytes:
        url = f"{self.GATEWAY}/ipfs/{cid}"
        try:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as ex:
            logger.error({"msg": "Request has been failed", "error": str(ex)})
            raise FetchError(cid) from ex
        return resp.content

    def _upload(self, content: bytes, name: str | None = None) -> str:
        raise UploadError

    def pin(self, cid: CID) -> None:
        raise PinError(cid)
