import hashlib

from .cid import CID, CIDv0
from .types import FetchError, IPFSProvider


class DummyIPFSProvider(IPFSProvider):
    """Dummy IPFS provider which using the local filesystem as a backend"""

    # pylint: disable=unreachable

    mempool: dict[CID, bytes]

    def __init__(self) -> None:
        self.mempool = {}

    def fetch(self, cid: CID) -> bytes:
        try:
            return self.mempool[cid]
        except KeyError:
            try:
                with open(str(cid), mode="r") as f:
                    return f.read().encode("utf-8")
            except Exception as e:
                raise FetchError(cid) from e

    def _upload(self, content: bytes, name: str | None = None) -> str:
        cid = "Qm" + hashlib.sha256(content).hexdigest()  # XXX: Dummy.
        self.mempool[CIDv0(cid)] = content
        return cid

    def pin(self, cid: CID) -> None:
        content = self.fetch(cid)

        with open(str(cid), mode="w", encoding="utf-8") as f:
            f.write(content.decode())
