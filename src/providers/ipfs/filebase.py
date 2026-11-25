from .kubo import Kubo


class Filebase(Kubo):
    """Client for [Filebase](https://filebase.com/) IPFS, Filebase supports Kubo API,
    so we can reuse Kubo implementation."""

    def __init__(self, host: str, rpc_port: int, *, timeout: int, token: str) -> None:
        super().__init__(host, rpc_port, timeout=timeout, token=token)
