import base64
import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode, urlparse

import requests

from src.providers.ipfs.cid import CIDv0, CIDv1, is_cid_v0

from .types import IPFSError, IPFSProvider, FetchError, PinError, UploadError

logger = logging.getLogger(__name__)


class GW3(IPFSProvider):
    """gw3.io client"""

    ENDPOINT = "https://gw3.io"

    def __init__(self, access_key: str, access_secret: str, *, timeout: int) -> None:
        super().__init__()
        self.access_key = access_key
        self.access_secret = base64.urlsafe_b64decode(access_secret)
        self.timeout = timeout

    def fetch(self, cid: CIDv0 | CIDv1):
        try:
            resp = self._send("GET", f"{self.ENDPOINT}/ipfs/{cid}")
        except IPFSError as ex:
            raise FetchError(cid) from ex
        return resp.content

    def upload(self, content: bytes, name: str | None = None) -> CIDv0 | CIDv1:
        url = self._auth_upload(len(content))
        try:
            response = requests.post(url, data=content, timeout=self.timeout)
            cid = response.headers["IPFS-Hash"]
        except IPFSError as ex:
            raise UploadError from ex
        except KeyError as ex:
            raise UploadError from ex

        return CIDv0(cid) if is_cid_v0(cid) else CIDv1(cid)

    def pin(self, cid: CIDv0 | CIDv1) -> None:
        try:
            self._send("POST", f"{self.ENDPOINT}/api/v0/pin/add", {"arg": str(cid)})
        except IPFSError as ex:
            raise PinError(cid) from ex

    def _auth_upload(self, size: int) -> str:
        try:
            response = self._send("POST", f"{self.ENDPOINT}/ipfs/", {"size": size})
            return response.json()["data"]["url"]
        except IPFSError as ex:
            raise UploadError from ex
        except KeyError as ex:
            raise UploadError from ex

    def _send(self, method: str, url: str, params: dict | None = None) -> requests.Response:
        req = self._signed_req(method, url, params)
        try:
            response = requests.Session().send(req, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as ex:
            logger.error({"msg": "Request has been failed", "error": str(ex)})
            raise IPFSError from ex
        return response

    def _signed_req(self, method: str, url: str, params: dict | None = None) -> requests.PreparedRequest:
        params = params or {}
        params["ts"] = str(int(time.time()))
        query = urlencode(params, doseq=True)

        parsed_url = urlparse(url)
        data = "\n".join((method, parsed_url.path, query)).encode("utf-8")
        mac = hmac.new(self.access_secret, data, hashlib.sha256)
        sign = base64.urlsafe_b64encode(mac.digest())

        req = requests.Request(method=method, url=url, params=params)
        req.headers["X-Access-Key"] = self.access_key
        req.headers["X-Access-Signature"] = sign.decode("utf-8")
        return req.prepare()
