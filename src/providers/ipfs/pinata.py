import logging
from json import JSONDecodeError
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from src.utils.jwt import validate_jwt

from .cid import CID
from .types import FetchError, IPFSProvider, UploadError

logger = logging.getLogger(__name__)


class Pinata(IPFSProvider):
    """pinata.cloud IPFS provider"""

    API_ENDPOINT = "https://api.pinata.cloud"
    PUBLIC_GATEWAY = "https://gateway.pinata.cloud"
    MAX_DEDICATED_GATEWAY_RETRIES = 1

    def __init__(self, jwt_token: str, *, timeout: int, dedicated_gateway_url: str, dedicated_gateway_token: str) -> None:
        super().__init__()
        validate_jwt(jwt_token)
        self.timeout = timeout

        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {jwt_token}"

        dedicated_adapter = HTTPAdapter(max_retries=Retry(
            total=self.MAX_DEDICATED_GATEWAY_RETRIES,
            status_forcelist=list(range(400, 600)),
            backoff_factor=3.0,
        ))
        self.dedicated_session = requests.Session()
        self.dedicated_session.headers["x-pinata-gateway-token"] = dedicated_gateway_token
        self.dedicated_session.mount("https://", dedicated_adapter)
        self.dedicated_session.mount("http://", dedicated_adapter)

        self.dedicated_gateway_url = dedicated_gateway_url
        self.dedicated_gateway_token = dedicated_gateway_token

    def _fetch(self, cid: CID) -> bytes:
        try:
            return self._fetch_from_dedicated_gateway(cid)
        except requests.RequestException as ex:
            logger.warning({
                "msg": "Dedicated gateway failed after retries, trying public gateway",
                "error": str(ex)
            })
            return self._fetch_from_public_gateway(cid)

    def _fetch_from_dedicated_gateway(self, cid: CID) -> bytes:
        url = urljoin(self.dedicated_gateway_url, f"/ipfs/{cid}")
        resp = self.dedicated_session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.content

    def _fetch_from_public_gateway(self, cid: CID) -> bytes:
        url = urljoin(self.PUBLIC_GATEWAY, f'/ipfs/{cid}')
        try:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as ex:
            logger.error({"msg": "Request has been failed", "error": str(ex)})
            raise FetchError(cid) from ex
        return resp.content

    def _upload(self, content: bytes, name: str | None = None) -> str:
        """Pinata has no dedicated endpoint for uploading, so pinFileToIPFS is used"""
        url = urljoin(self.API_ENDPOINT, '/pinning/pinFileToIPFS')
        try:
            with self.session as s:
                resp = s.post(url, files={"file": content}, timeout=self.timeout)
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
        pass
