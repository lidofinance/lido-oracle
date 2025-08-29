from typing import Any, List, Optional, Union

from _typeshed import Incomplete
from eth_typing import URI as URI
from web3.providers import JSONBaseProvider
from web3.types import RPCEndpoint as RPCEndpoint
from web3.types import RPCResponse as RPCResponse
import requests

logger: Incomplete

class NoActiveProviderError(Exception): ...
class ProtocolNotSupported(Exception): ...

class MultiProvider(JSONBaseProvider):
    endpoint_uri: str
    def __init__(
        self,
        endpoint_urls: List[Union[URI, str]],
        request_kwargs: Optional[Any] = ...,
        session: Optional[Any] = ...,
        websocket_kwargs: Optional[Any] = ...,
        websocket_timeout: Optional[Any] = ...,
    ) -> None: ...
    def make_request(self, method: RPCEndpoint, params: Any) -> RPCResponse: ...

class MultiHTTPProvider(MultiProvider):
    def __init__(
        self,
        endpoint_urls: List[Union[URI, str]],
        request_kwargs: Optional[Any] = ...,
        session: Optional[Any] = ...,
    ) -> None: ...

class FallbackProvider(MultiProvider):
    def __init__(
        self,
        endpoint_urls: List[Union[URI, str]],
        request_kwargs: Optional[Any] = ...,
        session: Optional[Any] = ...,
    ) -> None: ...

class HTTPSessionManagerProxy:
    def __init__(
        self,
        chain_id: Union[int, str],
        uri: str,
        network: str,
        cache_size: int = ...,
        session_pool_max_workers: int = ...,
        layer: Optional[str] = ...,
        session: Optional[requests.Session] = ...,
    ) -> None: ...
    
    def get_response_from_get_request(
        self,
        endpoint: str,
        params: Optional[Any] = ...,
        timeout: Optional[Any] = ...,
        stream: bool = ...,
    ) -> Any: ...
    
    def get_response_from_post_request(
        self,
        endpoint: str,
        data: Optional[Any] = ...,
        timeout: Optional[Any] = ...,
    ) -> Any: ...
    
    def json_make_get_request(
        self,
        endpoint: str,
        params: Optional[Any] = ...,
        timeout: Optional[Any] = ...,
    ) -> Any: ...
    
    def json_make_post_request(
        self,
        endpoint: str,
        data: Optional[Any] = ...,
        timeout: Optional[Any] = ...,
    ) -> Any: ...
    
    _uri: str
