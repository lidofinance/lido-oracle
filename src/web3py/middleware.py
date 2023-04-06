import json
import logging
import os
from typing import Any, Callable
from urllib.parse import urlparse

from requests import HTTPError, Response
from web3.types import RPCEndpoint, RPCResponse
from web3_multi_provider import NoActiveProviderError

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

    contracts = []

    abi_dir = './assets/'
    for filename in os.listdir(abi_dir):
        with open(os.path.join(abi_dir, filename), 'r') as f:
            try:
                contracts.append(w3.eth.contract(abi=json.load(f)))
            except json.JSONDecodeError:
                pass

    def middleware(method: RPCEndpoint, params: Any) -> RPCResponse:
        try:
            # Works only with HTTP and Websocket Provider
            domain = urlparse(getattr(w3.provider, "endpoint_uri")).netloc
        except:
            domain = 'unavailable'

        call_method = ''
        call_to = ''
        if method == 'eth_call':
            args = params[0]
            call_to = args['to']
            for contract in contracts:
                try:
                    call_method = contract.get_function_by_selector(args['data']).fn_name
                except ValueError:
                    pass
                if call_method:
                    break
        if method == 'eth_getBalance':
            call_to = params[0]

        with EL_REQUESTS_DURATION.time() as t:
            try:
                response = make_request(method, params)
            except HTTPError as ex:
                failed: Response = ex.response
                t.labels(
                    endpoint=method,
                    call_method=call_method,
                    call_to=call_to,
                    code=failed.status_code,
                    domain=domain,
                )
                raise ex
            except NoActiveProviderError:
                t.labels(
                    endpoint=method,
                    call_method=call_method,
                    call_to=call_to,
                    code=None,
                    domain=domain,
                )
                raise

            # https://www.jsonrpc.org/specification#error_object
            error = response.get("error")
            code: int = 0
            if isinstance(error, dict):
                code = error.get("code") or code

            t.labels(
                endpoint=method,
                call_method=call_method,
                call_to=call_to,
                code=code,
                domain=domain,
            )

            return response

    return middleware
