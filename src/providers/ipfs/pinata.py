import logging
import requests

from .cid import CIDv0, CIDv1, is_cid_v0
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
        url = f"{self.API_ENDPOINT}/pinning/pinFileToIPFS"
        try:
            with self.session as s:
                resp = s.post(url, files={"file": content})
                resp.raise_for_status()
        except requests.RequestException as ex:
            logger.error({"msg": "Request has been failed", "error": str(ex)})
            raise UploadError from ex
        cid = resp.json()["IpfsHash"]
        return CIDv0(cid) if is_cid_v0(cid) else CIDv1(cid)

    def pin(self, cid: CIDv0 | CIDv1) -> None:
        url = f"{self.API_ENDPOINT}/pinning/pinByHash"
        try:
            with self.session as s:
                resp = s.post(url, json={"hashToPin": str(cid)})
                resp.raise_for_status()
        except requests.RequestException as ex:
            logger.error({"msg": "Request has been failed", "error": str(ex)})
            raise PinError(cid) from ex
