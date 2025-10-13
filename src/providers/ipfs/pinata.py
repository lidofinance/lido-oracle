import logging
from json import JSONDecodeError
from urllib.parse import urljoin

import requests

from src.utils.jwt import validate_jwt

from .cid import CID
from .types import FetchError, IPFSProvider, PinError, UploadError

logger = logging.getLogger(__name__)


class Pinata(IPFSProvider):
    """pinata.cloud IPFS provider"""

    API_ENDPOINT = "https://api.pinata.cloud"
    PUBLIC_GATEWAY = "https://gateway.pinata.cloud"

    def __init__(self, jwt_token: str, *, timeout: int, dedicated_gateway_url: str, dedicated_gateway_token: str) -> None:
        super().__init__()
        validate_jwt(jwt_token)
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {jwt_token}"
        self.dedicated_gateway_url = dedicated_gateway_url
        self.dedicated_gateway_token = dedicated_gateway_token
        self.max_dedicated_gateway_failures = 2

    def fetch(self, cid: CID) -> bytes:
        for attempt in range(self.max_dedicated_gateway_failures):
            try:
                return self._fetch_from_dedicated_gateway(cid)
            except requests.RequestException as ex:
                logger.warning({
                    "msg": "Dedicated gateway failed, trying public gateway",
                    "error": str(ex),
                    "failures": attempt + 1
                })

        return self._fetch_from_public_gateway(cid)

    def _fetch_from_dedicated_gateway(self, cid: CID) -> bytes:
        url = urljoin(self.dedicated_gateway_url, f"/ipfs/{cid}")
        headers = {"x-pinata-gateway-token": self.dedicated_gateway_token}

        resp = requests.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.content

    def _fetch_from_public_gateway(self, cid: CID) -> bytes:
        url = f"{self.PUBLIC_GATEWAY}/ipfs/{cid}"
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
