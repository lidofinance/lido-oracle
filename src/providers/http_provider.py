import logging
from abc import ABC, abstractmethod
from http import HTTPStatus
from typing import Any, Callable, NoReturn, Protocol, Sequence
from urllib.parse import urljoin, urlparse

# NOTE: Missing library stubs or py.typed marker. That's why we use `type: ignore`
from json_stream import requests as json_stream_requests  # type: ignore
from json_stream.base import TransientStreamingJSONObject  # type: ignore
from prometheus_client import Histogram
from requests import JSONDecodeError, Session
from requests.adapters import HTTPAdapter
from urllib3 import Retry
from web3_multi_provider import HTTPSessionManagerProxy

from src.providers.consistency import ProviderConsistencyModule

logger = logging.getLogger(__name__)


class NoHostsProvided(Exception):
    pass


class NotOkResponse(Exception):
    status: int
    text: str

    def __init__(self, *args, status: int, text: str):
        self.status = status
        self.text = text
        super().__init__(*args)


class ReturnValueValidator(Protocol):
    def __call__(self, data: Any, meta: dict, *, endpoint: str) -> None | NoReturn: ...


def data_is_any(data: Any, meta: dict, *, endpoint: str):
    pass


def data_is_dict(data: Any, meta: dict, *, endpoint: str):
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping response from {endpoint}")


def data_is_list(data: Any, meta: dict, *, endpoint: str):
    if not isinstance(data, list):
        raise ValueError(f"Expected list response from {endpoint}")


def data_is_transient_dict(data: Any, meta: dict, *, endpoint: str):
    if not isinstance(data, TransientStreamingJSONObject):
        raise ValueError(f"Expected mapping response from {endpoint}")


class BaseHTTPProvider(ProviderConsistencyModule, ABC):
    """
    Base HTTP Provider with metrics and retry strategy integrated inside.
    """

    PROMETHEUS_HISTOGRAM: Histogram
    request_timeout: int

    PROVIDER_EXCEPTION = NotOkResponse

    def __init__(
        self,
        hosts: list[str],
        request_timeout: int,
        retry_total: int,
        retry_backoff_factor: int,
    ):
        if not hosts:
            raise NoHostsProvided(f"No hosts provided for {self.__class__.__name__}")

        self.hosts = hosts
        self.request_timeout = request_timeout
        self.retry_count = retry_total
        self.backoff_factor = retry_backoff_factor

        retry_strategy = Retry(
            total=self.retry_count,
            status_forcelist=[418, 429, 500, 502, 503, 504],
            backoff_factor=self.backoff_factor,
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
        self,
        endpoint: str,
        path_params: Sequence[str | int] | None = None,
        query_params: dict | None = None,
        force_raise: Callable[..., Exception | None] = lambda _: None,
        retval_validator: ReturnValueValidator = data_is_any,
        stream: bool = False,
    ) -> tuple[Any, dict]:
        """
        Get plain or streamed request with fallbacks
        Returns (data, meta) or raises exception

        force_raise - function that returns an Exception if it should be thrown immediately.
        Sometimes NotOk response from first provider is the response that we are expecting.
        """
        errors: list[Exception] = []

        if path_params:
            endpoint = endpoint.format(*path_params)

        for host in self.hosts:
            try:
                return self._get_without_fallbacks(
                    host,
                    endpoint,
                    query_params,
                    stream=stream,
                    retval_validator=retval_validator,
                )
            except Exception as e:  # pylint: disable=W0703
                errors.append(e)

                # Check if exception should be raised immediately
                if to_force_raise := force_raise(errors):
                    raise to_force_raise from e

                logger.warning(
                    {
                        'msg': f'[{self.__class__.__name__}] Host [{urlparse(host).netloc}] responded with error',
                        'error': str(e),
                        'provider': urlparse(host).netloc,
                    }
                )

        # Raise error from last provider.
        raise errors[-1]

    @abstractmethod
    def _get_without_fallbacks(
        self,
        provider: Any,
        endpoint: str,
        query_params: dict | None = None,
        stream: bool = False,
        retval_validator: ReturnValueValidator = data_is_any,
    ) -> tuple[Any, dict]:
        """
        Simple get request without fallbacks
        Returns (data, meta) or raises an exception
        """
        raise NotImplementedError

    def get_all_providers(self) -> list[str]:
        return self.hosts

    @abstractmethod
    def _get_chain_id_with_provider(self, provider_index: int) -> int:
        raise NotImplementedError("_get_chain_id_with_provider should be implemented")


class HTTPProvider(BaseHTTPProvider):
    """
    HTTP Provider with HTTPSessionManagerProxy for consensus layer clients.
    """

    managers: list[HTTPSessionManagerProxy]

    def __init__(
        self,
        hosts: list[str],
        request_timeout: int,
        retry_total: int,
        retry_backoff_factor: int,
    ):
        super().__init__(hosts, request_timeout, retry_total, retry_backoff_factor)

        self.managers = [
            HTTPSessionManagerProxy(
                chain_id=1,
                uri=h,
                network="ethereum",
                layer="cl",
                session=self.session,
            ) for h in hosts
        ]

    def _get(
        self,
        endpoint: str,
        path_params: Sequence[str | int] | None = None,
        query_params: dict | None = None,
        force_raise: Callable[..., Exception | None] = lambda _: None,
        retval_validator: ReturnValueValidator = data_is_any,
        stream: bool = False,
    ) -> tuple[Any, dict]:
        """
        Get plain or streamed request with fallbacks
        Returns (data, meta) or raises exception

        force_raise - function that returns an Exception if it should be thrown immediately.
        Sometimes NotOk response from first provider is the response that we are expecting.
        """
        errors: list[Exception] = []

        if path_params:
            endpoint = endpoint.format(*path_params)

        for manager in self.managers:
            try:
                return self._get_without_fallbacks(
                    manager,
                    endpoint,
                    query_params,
                    stream=stream,
                    retval_validator=retval_validator,
                )
            except Exception as e:  # pylint: disable=W0703
                errors.append(e)

                # Check if exception should be raised immediately
                if to_force_raise := force_raise(errors):
                    raise to_force_raise from e

                logger.warning(
                    {
                        'msg': f'[{self.__class__.__name__}] Host [{urlparse(manager._uri).netloc}] responded with error',  # pylint: disable=protected-access
                        'error': str(e),
                        'provider': urlparse(manager._uri).netloc,  # pylint: disable=protected-access
                    }
                )

        # Raise error from last provider.
        raise errors[-1]

    def _get_without_fallbacks(
        self,
        provider: HTTPSessionManagerProxy,
        endpoint: str,
        query_params: dict | None = None,
        stream: bool = False,
        retval_validator: ReturnValueValidator = data_is_any,
    ) -> tuple[Any, dict]:
        """
        Simple get request without fallbacks using HTTPSessionManagerProxy
        Returns (data, meta) or raises an exception
        """
        host = provider._uri  # pylint: disable=protected-access
        complete_endpoint = self._urljoin(host, endpoint)

        with self.PROMETHEUS_HISTOGRAM.time() as t:
            try:
                response, status_code, text = self._make_request(provider, complete_endpoint, query_params, stream)
            except Exception as error:
                logger.error({'msg': str(error)})
                t.labels(
                    endpoint=endpoint,
                    code=0,
                    domain=urlparse(host).netloc,
                )
                raise self.PROVIDER_EXCEPTION(status=0, text='Response error.') from error

            t.labels(
                endpoint=endpoint,
                code=status_code,
                domain=urlparse(host).netloc,
            )

            if status_code != HTTPStatus.OK:
                response_fail_msg = (
                    f'Response from {complete_endpoint} [{status_code}]'
                    f' with text: "{text}" returned.'
                )
                logger.debug({'msg': response_fail_msg})
                raise self.PROVIDER_EXCEPTION(response_fail_msg, status=status_code, text=text)

            try:
                if stream:
                    # There's no guarantee the JSON is valid at this point.
                    json_response = response
                else:
                    json_response = response
            except JSONDecodeError as error:
                response_fail_msg = (
                    f'Failed to decode JSON response from {complete_endpoint} with text: "{text}"'
                )
                logger.debug({'msg': response_fail_msg})
                raise self.PROVIDER_EXCEPTION(status=0, text='JSON decode error.') from error

        try:
            data = json_response["data"]
            meta = {}

            if not stream:
                del json_response["data"]
                meta = json_response
        except KeyError:
            # NOTE: Used by KeysAPIClient only.
            data = json_response
            meta = {}

        retval_validator(data, meta, endpoint=endpoint)
        return data, meta

    def _make_request(self, provider: HTTPSessionManagerProxy, complete_endpoint: str, query_params: dict | None, stream: bool) -> tuple[Any, int, str]:
        """Make HTTP request using HTTPSessionManagerProxy"""
        response = provider.get_response_from_get_request(
            complete_endpoint,
            params=query_params,
            timeout=self.request_timeout,
            stream=stream,
        )

        # Get text before consuming stream
        response_text = ""
        try:
            if stream:
                json_response = json_stream_requests.load(response)
                # For streaming responses, we can't get the full text after consumption
                response_text = f"<streaming response {response.status_code}>"
            else:
                json_response = response.json()
                response_text = response.text
        except JSONDecodeError as error:
            response_text = getattr(response, 'text', str(error))
            raise JSONDecodeError("JSON decode error", response_text, 0) from error

        return json_response, response.status_code, response_text

    def _get_chain_id_with_provider(self, provider_index: int) -> int:
        raise NotImplementedError("HTTPProvider subclasses should implement _get_chain_id_with_provider")


class SimpleHTTPProvider(BaseHTTPProvider):
    """
    Simple HTTP Provider using regular requests for Keys API clients.
    """

    def _get_without_fallbacks(
        self,
        provider: str,
        endpoint: str,
        query_params: dict | None = None,
        stream: bool = False,
        retval_validator: ReturnValueValidator = data_is_any,
    ) -> tuple[Any, dict]:
        """
        Simple get request without fallbacks using regular requests session
        Returns (data, meta) or raises an exception
        """
        complete_endpoint = self._urljoin(provider, endpoint)

        with self.PROMETHEUS_HISTOGRAM.time() as t:
            try:
                response, status_code, text = self._make_request(provider, complete_endpoint, query_params, stream)
            except Exception as error:
                logger.error({'msg': str(error)})
                t.labels(
                    endpoint=endpoint,
                    code=0,
                    domain=urlparse(provider).netloc,
                )
                raise self.PROVIDER_EXCEPTION(status=0, text='Response error.') from error

            t.labels(
                endpoint=endpoint,
                code=status_code,
                domain=urlparse(provider).netloc,
            )

            if status_code != HTTPStatus.OK:
                response_fail_msg = (
                    f'Response from {complete_endpoint} [{status_code}]'
                    f' with text: "{text}" returned.'
                )
                logger.debug({'msg': response_fail_msg})
                raise self.PROVIDER_EXCEPTION(response_fail_msg, status=status_code, text=text)

            try:
                if stream:
                    # There's no guarantee the JSON is valid at this point.
                    json_response = response
                else:
                    json_response = response
            except JSONDecodeError as error:
                response_fail_msg = (
                    f'Failed to decode JSON response from {complete_endpoint} with text: "{text}"'
                )
                logger.debug({'msg': response_fail_msg})
                raise self.PROVIDER_EXCEPTION(status=0, text='JSON decode error.') from error

        try:
            data = json_response["data"]
            meta = {}

            if not stream:
                del json_response["data"]
                meta = json_response
        except KeyError:
            # NOTE: Used by KeysAPIClient only.
            data = json_response
            meta = {}

        retval_validator(data, meta, endpoint=endpoint)
        return data, meta

    def _make_request(self, provider: str, complete_endpoint: str, query_params: dict | None, stream: bool) -> tuple[Any, int, str]:
        """Make HTTP request using regular requests session"""
        response = self.session.get(
            complete_endpoint,
            params=query_params,
            timeout=self.request_timeout,
            stream=stream,
        )

        try:
            if stream:
                json_response = json_stream_requests.load(response)
            else:
                json_response = response.json()
        except JSONDecodeError as error:
            raise JSONDecodeError("JSON decode error", response.text, 0) from error

        return json_response, response.status_code, response.text

    def _get_chain_id_with_provider(self, provider_index: int) -> int:
        raise NotImplementedError("SimpleHTTPProvider subclasses should implement _get_chain_id_with_provider")
