import time
from collections.abc import Callable

from requests import Response

from src.metrics.prometheus.basic import EXTERNAL_API_REQUESTS_DURATION


def send_external_api_request[**P](
    service: str,
    method: str,
    send: Callable[P, Response],
    *args: P.args,
    **kwargs: P.kwargs,
) -> Response:
    """Send a request and record its duration and status code.

    Code 0 means that the call ended without a response: a connection error, a timeout, exhausted retries.
    """
    code = 0
    start = time.perf_counter()
    try:
        response = send(*args, **kwargs)
        code = response.status_code
        return response
    finally:
        EXTERNAL_API_REQUESTS_DURATION.labels(service=service, method=method, code=code).observe(
            time.perf_counter() - start
        )
