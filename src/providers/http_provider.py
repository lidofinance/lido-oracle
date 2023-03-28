import logging
from abc import ABC
from http import HTTPStatus
from typing import Optional, Tuple, Sequence
from urllib.parse import urljoin, urlparse

from prometheus_client import Histogram
from requests import Session, JSONDecodeError, Timeout
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from src.variables import HTTP_REQUEST_RETRY_COUNT, HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS, HTTP_REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


class NoActiveProviderError(Exception):
    """Base exception if all providers are offline"""


class NotOkResponse(Exception):
    status: int
    text: str

    def __init__(self, *args, status: int, text: str):
        self.status = status
        self.text = text
        super().__init__(*args)


class HTTPProvider(ABC):
    PROMETHEUS_HISTOGRAM: Histogram

    def __init__(self, hosts: list[str]):
        self.hosts = hosts

        retry_strategy = Retry(
            total=HTTP_REQUEST_RETRY_COUNT,
            status_forcelist=[418, 429, 500, 502, 503, 504],
            backoff_factor=HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS,
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session = Session()
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    @staticmethod
    def _urljoin(host, url):
        if not host.endswith('/'):
            host += '/'
        return urljoin(host, url)

    def _get(
        self, endpoint: str, path_params: Optional[Sequence[str | int]] = None, query_params: Optional[dict] = None
    ) -> Tuple[dict | list, dict]:
        """
        Get request with fallbacks
        Returns (data, meta) or raises exception
        """
        error = None
        for host in self.hosts:
            try:
                return self._simple_get(host, endpoint, path_params, query_params)
            except Exception as e:  # pylint: disable=W0703
                logger.warning(
                    {
                        "msg": "Host not responding.",
                        "error": str(e),
                        "provider": urlparse(host).netloc,
                    }
                )
                error = e
        msg = f"No active host available for {self.__class__.__name__}"
        logger.error({"msg": msg})
        raise NoActiveProviderError(msg) from error

    def _simple_get(
        self,
        host: str,
        endpoint: str,
        path_params: Optional[Sequence[str | int]] = None,
        query_params: Optional[dict] = None
    ) -> Tuple[dict | list, dict]:
        """
        Simple get request without fallbacks
        Returns (data, meta) or raises exception
        """
        with self.PROMETHEUS_HISTOGRAM.time() as t:
            try:
                response = self.session.get(
                    self._urljoin(host, endpoint.format(*path_params) if path_params else endpoint),
                    params=query_params,
                    timeout=HTTP_REQUEST_TIMEOUT,
                )
            except Timeout as error:
                msg = "Timeout error."
                logger.debug({'msg': msg})
                t.labels(
                    endpoint=endpoint,
                    code=0,
                    domain=urlparse(host).netloc,
                )
                raise TimeoutError(msg) from error

            try:
                if response.status_code != HTTPStatus.OK:
                    msg = f'Response [{response.status_code}] with text: "{str(response.text)}" returned.'
                    logger.debug({'msg': msg})
                    raise NotOkResponse(msg, status=response.status_code, text=response.text)

                json_response = response.json()
            except JSONDecodeError as error:
                msg = f'Response [{response.status_code}] with text: "{str(response.text)}" returned.'
                logger.debug({'msg': msg})
                raise error
            finally:
                t.labels(
                    endpoint=endpoint,
                    code=response.status_code,
                    domain=urlparse(host).netloc,
                )

        if 'data' in json_response:
            data = json_response['data']
            del json_response['data']
            meta = json_response
        else:
            data = json_response
            meta = {}
        return data, meta
