from typing import Any, List, Optional, Union

from _typeshed import Incomplete
from eth_typing import URI as URI
from web3.providers import JSONBaseProvider
from web3.types import RPCEndpoint as RPCEndpoint
from web3.types import RPCResponse as RPCResponse

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
