import json
import logging
import os
from typing import Any, Union
from urllib.parse import urlparse

from requests import HTTPError, Response
from web3 import Web3
from web3.middleware import Web3Middleware
from web3.types import RPCEndpoint, RPCResponse
from web3_multi_provider import NoActiveProviderError

from src.metrics.prometheus.basic import EL_REQUESTS_DURATION

logger = logging.getLogger(__name__)


class Web3MetricsMiddleware(Web3Middleware):

    def __init__(self, w3: Union["AsyncWeb3", "Web3"]):
        super().__init__(w3)
        self.contracts = []
        abi_dir = './assets/'
        for filename in os.listdir(abi_dir):
            with open(os.path.join(abi_dir, filename), 'r') as f:
                try:
                    self.contracts.append(self._w3.eth.contract(abi=json.load(f)))
                except json.JSONDecodeError:  # pragma: no cover
                    pass

    def wrap_make_request(self, make_request):

        def middleware(method: RPCEndpoint, params: Any) -> RPCResponse:
            try:
                # Works only with HTTP and Websocket Provider
                domain = urlparse(getattr(self._w3.provider, "endpoint_uri")).netloc
            except:
                domain = 'unavailable'

            call_method = ''
            call_to = ''
            if method == 'eth_call':
                args = params[0]
                call_to = args['to']
                for contract in self.contracts:
                    try:
                        call_method = contract.get_function_by_selector(args['data']).fn_name
                    except ValueError:  # pragma: no cover
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


def add_requests_metric_middleware(web3: Web3):
    web3.middleware_onion.add(Web3MetricsMiddleware, 'metrics_middleware')
