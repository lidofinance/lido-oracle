import logging
from json import JSONDecodeError
from urllib.parse import urljoin

import requests

from .cid import CID
from .types import FetchError, IPFSProvider, UploadError
from ...utils.version import get_oracle_version

logger = logging.getLogger(__name__)


class LidoIPFS(IPFSProvider):

    RPC_UNIXFS_ADD_ARGS: dict[str, int | str] = {
        "chunker": "size-262144",
        "hash": "sha2-256",
        "cid-version": 0,
        "trickle": "false",
        "raw-leaves": "false",
    }

    def __init__(self, host: str, token: str, timeout: int = 30) -> None:
        super().__init__()
        self.host = host
        self.token = token
        self.timeout = timeout

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": f"Lido-Oracle/v{get_oracle_version()}"
        }

    def _fetch(self, cid: CID) -> bytes:
        """Fetch content by CID from Lido IPFS node.

        Warning! This provider can only fetch content uploaded directly to
        the Lido IPFS node. It cannot fetch files from the global IPFS network.

        """
        url = urljoin(self.host, f"/ipfs/{cid}")
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as ex:
            logger.error({"msg": "Request has been failed", "error": str(ex)})
            raise FetchError(cid) from ex
        return resp.content

    def _upload(self, content: bytes, name: str | None = None) -> str:
        """Upload content to Lido IPFS node with automatic pinning."""
        url = urljoin(self.host, "/add")
        filename = name or "file"

        params = {
            **self.RPC_UNIXFS_ADD_ARGS,
            "name": filename,
            "replication-min": 3,
            "replication-max": 3,
        }

        try:
            response = requests.post(
                url,
                files={"file": content},
                params=params,
                headers=self._get_headers(),
                timeout=self.timeout
            )
            response.raise_for_status()
        except requests.RequestException as ex:
            logger.error({"msg": "Upload request failed", "error": str(ex)})
            raise UploadError from ex

        try:
            return response.json()["cid"]
        except (JSONDecodeError, KeyError) as ex:
            logger.error({"msg": "Invalid response format", "response": response.text})
            raise UploadError from ex

    def pin(self, cid: CID) -> None:
        pass
