import logging
from json import JSONDecodeError

import requests

from .cid import CID
from .types import FetchError, IPFSProvider, PinError, UploadError

logger = logging.getLogger(__name__)


class Pinata(IPFSProvider):
    """pinata.cloud IPFS provider"""

    API_ENDPOINT = "https://api.pinata.cloud"
    GATEWAY = "https://gateway.pinata.cloud"

    def __init__(self, jwt_token: str, *, timeout: int) -> None:
        super().__init__()
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {jwt_token}"

    def fetch(self, cid: CID) -> bytes:
        url = f"{self.GATEWAY}/ipfs/{cid}"
        try:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as ex:
            logger.error({"msg": "Request has been failed", "error": str(ex)})
            raise FetchError(cid) from ex
        return resp.content

    def publish(self, content: bytes, name: str | None = None) -> CID:
        # NOTE: The content is pinned by the `upload` method.
        return self.upload(content)

    def _upload(self, content: bytes, name: str | None = None) -> str:
        """Pinata has no dedicated endpoint for uploading, so pinFileToIPFS is used"""

        url = f"{self.API_ENDPOINT}/pinning/pinFileToIPFS"
        try:
            with self.session as s:
                resp = s.post(url, files={"file": content})
                resp.raise_for_status()
        except requests.RequestException as ex:
            logger.error({"msg": "Request has been failed", "error": str(ex)})
            raise UploadError from ex
        try:
            cid = resp.json()["IpfsHash"]
        except JSONDecodeError as ex:
            raise UploadError from ex
        except KeyError as ex:
            raise UploadError from ex

        return cid

    def pin(self, cid: CID) -> None:
        """pinByHash is a paid feature"""
        raise PinError(cid)
