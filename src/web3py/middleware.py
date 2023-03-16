import logging
from typing import Any, Callable
from urllib.parse import urlparse

from requests import HTTPError, Response
from web3 import Web3
from web3.types import RPCEndpoint, RPCResponse

from src.metrics.prometheus.basic import EL_REQUESTS_DURATION


logger = logging.getLogger(__name__)


def metrics_collector(
    make_request: Callable[[RPCEndpoint, Any], RPCResponse],
    w3: Web3,
) -> Callable[[RPCEndpoint, Any], RPCResponse]:
    """
    Works correctly with MultiProvider and vanilla Providers.

    EL_REQUESTS_DURATION - HISTOGRAM with requests time, count, response codes and request domain.
    """

    def middleware(method: RPCEndpoint, params: Any) -> RPCResponse:
        try:
            # Works only with HTTP and Websocket Provider
            domain = urlparse(getattr(w3.provider, "endpoint_uri")).netloc
        except:
            domain = 'unavailable'

        with EL_REQUESTS_DURATION.time() as t:
            try:
                response = make_request(method, params)
            except HTTPError as ex:
                failed: Response = ex.response
                t.labels(
                    method=method,
                    code=failed.status_code,
                    domain=domain,
                )
                raise

            # https://www.jsonrpc.org/specification#error_object
            # https://eth.wiki/json-rpc/json-rpc-error-codes-improvement-proposal
            error = response.get("error")
            code: int = 0
            if isinstance(error, dict):
                code = error.get("code") or code

            t.labels(
                name=method,
                code=code,
                domain=domain,
            )

            return response

    return middleware
