from src.providers.ipfs.kubo import Kubo


class Filebase(Kubo):
    """Client for [Filebase](https://filebase.com/) IPFS"""

    def __init__(self, host: str, rpc_port: int, *, timeout: int, token: str) -> None:
        super().__init__(host, rpc_port, timeout=timeout, token=token)