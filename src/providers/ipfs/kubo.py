# pylint: disable=duplicate-code

import logging
from json import JSONDecodeError

import requests

from .cid import CID
from .types import FetchError, IPFSProvider, PinError, UploadError


logger = logging.getLogger(__name__)


class Kubo(IPFSProvider):
    """Client for [Kubo](https://github.com/ipfs/kubo) IPFS"""

    # @see https://docs.ipfs.tech/reference/kubo/rpc/#api-v0-add
    RPC_UNIXFS_ADD_ARGS: dict[str, int | str] = {
        "chunker": "size-262144",
        "hash": "sha2-256",
        "cid-version": 0,
        "trickle": "false",
        "raw-leaves": "false",
    }

    def __init__(self, host: str, rpc_port: int, *, timeout: int, token: str | None = None) -> None:
        super().__init__()
        self.endpoint = f"{host}:{rpc_port}"
        self.timeout = timeout
        self.token = token

    def _headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    def _fetch(self, cid: CID) -> bytes:
        # @see https://docs.ipfs.tech/reference/kubo/rpc/#api-v0-cat
        url = f"{self.endpoint}/api/v0/cat"
        try:
            resp = requests.post(url, timeout=self.timeout, params={"arg": str(cid)}, headers=self._headers())
            resp.raise_for_status()
        except requests.RequestException as ex:
            logger.error({"msg": "Request has been failed", "error": str(ex)})
            raise FetchError(cid) from ex
        return resp.content

    def _upload(self, content: bytes, name: str | None = None) -> str:
        # @see https://docs.ipfs.tech/reference/kubo/rpc/#api-v0-add
        url = f"{self.endpoint}/api/v0/add"
        name = name or "file"  # The name doesn't make any difference.

        try:
            resp = requests.post(
                url,
                files={name: (name, content, "application/octet-stream")},
                params=self.RPC_UNIXFS_ADD_ARGS,
                headers=self._headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as ex:
            logger.error({"msg": "Request has been failed", "error": str(ex)})
            raise UploadError from ex

        try:
            return resp.json()["Hash"]
        except JSONDecodeError as ex:
            raise UploadError from ex
        except KeyError as ex:
            raise UploadError from ex

    def pin(self, cid: CID) -> None:
        # @see https://docs.ipfs.tech/reference/kubo/rpc/#api-v0-pin-add
        url = f"{self.endpoint}/api/v0/pin/add"
        try:
            resp = requests.post(url, params={"arg": str(cid)}, headers=self._headers(), timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as ex:
            logger.error({"msg": "Request has been failed", "error": str(ex)})
            raise PinError(cid) from ex

        try:
            pinned = resp.json()["Pins"][0]
        except JSONDecodeError as ex:
            raise UploadError from ex
        except (KeyError, IndexError) as ex:
            raise UploadError from ex

        if str(cid) != pinned:
            raise PinError(cid) from ValueError(f"Got unexpected pinned CID={pinned}")
