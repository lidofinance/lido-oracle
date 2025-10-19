from typing import List
from multiformats import CID

class PBLink:
    def __init__(
        self,
        hash: CID,
        name: str = "",
        size: int = 0
    ) -> None: ...

class PBNode:
    def __init__(
        self,
        data: bytes | None = None,
        links: List[PBLink] | None = None
    ) -> None: ...

def encode(node: PBNode) -> bytes: ...
