import base64
import hashlib
import hmac
import logging
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

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
        url = f"{self.ENDPOINT}/ipfs/{cid}"
        req = requests.Request("GET", url)
        try:
            response = self._send(req)
            return response.content
        except IPFSError as ex:
            raise FetchError(cid) from ex

    def upload(self, content: bytes, name: str | None = None) -> CIDv0 | CIDv1:
        url = self._auth_upload(len(content))
        try:
            response = requests.post(url, data=content, timeout=self.timeout)
        except IPFSError as ex:
            raise UploadError from ex
        cid = response.headers["IPFS-Hash"]
        return CIDv0(cid) if is_cid_v0(cid) else CIDv1(cid)

    def pin(self, cid: CIDv0 | CIDv1) -> None:
        url = f"{self.ENDPOINT}/api/v0/pin/add?arg={cid}"
        req = requests.Request("POST", url)
        try:
            self._send(req)
        except IPFSError as ex:
            raise PinError(cid) from ex

    def _auth_upload(self, size: int) -> str:
        url = f"{self.ENDPOINT}/ipfs/?size={size}"
        req = requests.Request("POST", url)
        try:
            response = self._send(req)
            response.raise_for_status()
        except IPFSError as ex:
            raise UploadError from ex
        return response.json()["data"]["url"]

    def _send(self, req: requests.Request):
        prepped = self._sign(req.prepare())
        try:
            response = requests.Session().send(prepped, timeout=self.timeout)
            response.raise_for_status()
            return response
        except requests.RequestException as ex:
            logger.error({"msg": "Request has been failed", "error": str(ex)})
            raise IPFSError from ex

    def _sign(self, req: requests.PreparedRequest) -> requests.PreparedRequest:
        if not req.url or not req.method:
            raise RuntimeError(f"Invalid {repr(req)} given")

        url = urlparse(req.url)
        args = dict(parse_qsl(url.query))
        args["ts"] = str(int(time.time()))
        query = urlencode(args, doseq=True)

        data = "\n".join((req.method, url.path, query)).encode("utf-8")
        mac = hmac.new(self.access_secret, data, hashlib.sha256)
        sign = base64.urlsafe_b64encode(mac.digest())

        req.url = urlunparse(url._replace(query=query))
        req.headers["X-Access-Key"] = self.access_key
        req.headers["X-Access-Signature"] = sign.decode("utf-8")
        return req
