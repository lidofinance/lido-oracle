import hashlib

from web3 import Web3
from web3.module import Module

from .types import CIDv0, CIDv1, IPFSProvider, NotFound


class DummyIPFSProvider(IPFSProvider, Module):
    """Dummy IPFS provider which using the local filesystem as a backend"""

    mempool: dict[CIDv0 | CIDv1, bytes]

    def __init__(self, w3: Web3) -> None:
        super().__init__(w3)
        self.mempool = {}

    def fetch(self, cid: CIDv0 | CIDv1) -> bytes:
        try:
            return self.mempool[cid]
        except KeyError:
            try:
                with open(cid, mode="r")  as f:
                    return f.read().encode("utf-8")
            except Exception as e:
                raise NotFound() from e


    def upload(self, content: bytes, name: str | None = None) -> CIDv0 | CIDv1:
        cid = CIDv0("Qm" + hashlib.sha256(content).hexdigest())  # XXX: Dummy.
        self.mempool[cid] = content
        return cid

    def pin(self, cid: CIDv0 | CIDv1) -> None:
        content = self.fetch(cid)

        with open(cid, mode="w", encoding="utf-8") as f:
            f.write(content.decode())