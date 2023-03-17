import logging
from typing import Any, Callable
from urllib.parse import urlparse

from requests import HTTPError, Response
from web3.types import RPCEndpoint, RPCResponse

from src.metrics.prometheus.basic import EL_REQUESTS_DURATION
from web3 import Web3

logger = logging.getLogger(__name__)


def metrics_collector(
    make_request: Callable[[RPCEndpoint, Any], RPCResponse],
    w3: Web3,
) -> Callable[[RPCEndpoint, Any], RPCResponse]:
    """
    Works correctly with MultiProvider and vanilla Providers.

    EL_REQUESTS_DURATION - HISTOGRAM with requests time, count, response codes and request domain.
    """

    def middleware(endpoint_name: RPCEndpoint, params: Any) -> RPCResponse:
        try:
            # Works only with HTTP and Websocket Provider
            domain = urlparse(getattr(w3.provider, "endpoint_uri")).netloc
        except:
            domain = 'unavailable'

        call_method = ''
        call_to = ''
        if hasattr(w3, 'lido_contracts'):
            if endpoint_name == 'eth_call':
                args = params[0]
                call_to = args['to']
                if contract := w3.lido_contracts.contracts_dict.get(call_to, ''):
                    call_method = contract.get_function_by_selector(args['data']).fn_name
        if endpoint_name == 'eth_getBalance':
            call_to = params[0]

        with EL_REQUESTS_DURATION.time() as t:
            try:
                response = make_request(endpoint_name, params)
            except HTTPError as ex:
                failed: Response = ex.response
                t.labels(
                    endpoint=endpoint_name,
                    call_method=call_method,
                    call_to=call_to,
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
                endpoint=endpoint_name,
                call_method=call_method,
                call_to=call_to,
                code=code,
                domain=domain,
            )

            return response

    return middleware
