from typing import Any, Optional

from _typeshed import Incomplete

import requests
from aiohttp import ClientResponse
from eth_typing import URI as URI
from web3.providers import JSONBaseProvider
from web3.types import RPCEndpoint as RPCEndpoint, RPCResponse as RPCResponse
from web3._utils.http_session_manager import HTTPSessionManager

logger: Incomplete

class NoActiveProviderError(Exception): ...
class ProtocolNotSupported(Exception): ...

class MultiProvider(JSONBaseProvider):
    endpoint_uri: str
    def __init__(
        self,
        endpoint_urls: list[URI | str],
        request_kwargs: Any | None = ...,
        session: Any | None = ...,
        websocket_kwargs: Any | None = ...,
        websocket_timeout: Any | None = ...,
    ) -> None: ...
    def make_request(self, method: RPCEndpoint, params: Any) -> RPCResponse: ...

class FallbackProvider(MultiProvider):
    def __init__(
        self,
        endpoint_urls: list[URI | str],
        request_kwargs: Any | None = ...,
        session: Any | None = ...,
    ) -> None: ...

class HTTPSessionManagerProxy(HTTPSessionManager):
    def __init__(
        self,
        chain_id: int | str,
        uri: str,
        network: str,
        cache_size: int = 100,
        session_pool_max_workers: int = 5,
        layer: str | None = None,
        session: requests.Session | None = None,
    ): ...


    def _timed_call(self, func: Any, *args: Any, **kwargs: Any) -> requests.Response: ...

    def get_response_from_get_request(
        self, endpoint_uri: URI, *args: Any, **kwargs: Any
    ) -> requests.Response: ...

    def get_response_from_post_request(
        self, endpoint_uri: URI, *args: Any, **kwargs: Any
    ) -> requests.Response: ...

    async def async_get_response_from_get_request(
        self, endpoint_uri: URI, *args: Any, **kwargs: Any
    ) -> ClientResponse: ...

    async def async_get_response_from_post_request(
        self, endpoint_uri: URI, *args: Any, **kwargs: Any
    ) -> ClientResponse: ...