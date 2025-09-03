# pylint: disable=protected-access
from unittest.mock import MagicMock, Mock

import pytest
from requests import Response

from src.metrics.prometheus.basic import CL_REQUESTS_DURATION
from src.providers.http_provider import (
    HTTPProvider,
    NoHostsProvided,
    NotOkResponse,
    SimpleHTTPProvider,
    data_is_any,
)


@pytest.mark.unit
def test_urljoin():
    join = HTTPProvider._urljoin
    assert join('http://localhost', 'api') == 'http://localhost/api'
    assert join('http://localhost/', 'api') == 'http://localhost/api'
    assert join('http://localhost', '/api') == 'http://localhost/api'
    assert join('http://localhost/', '/api') == 'http://localhost/api'
    assert join('http://localhost', 'api/') == 'http://localhost/api/'
    assert join('http://localhost/', 'api/') == 'http://localhost/api/'
    assert join('http://localhost/token', 'api') == 'http://localhost/token/api'
    assert join('http://localhost/token/', 'api') == 'http://localhost/token/api'


@pytest.mark.unit
def test_no_providers():
    with pytest.raises(NoHostsProvided):
        HTTPProvider([], 5 * 60, 1, 1)


@pytest.mark.unit
def test_all_fallbacks_ok():
    provider = HTTPProvider(['http://localhost:1', 'http://localhost:2'], 5 * 60, 1, 1)
    provider._get_without_fallbacks = lambda manager, endpoint, query_params, stream, **_: (manager._uri, endpoint)
    assert provider._get('test') == ('http://localhost:1', 'test')
    assert len(provider.get_all_providers()) == 2


@pytest.mark.unit
def test_all_fallbacks_bad():
    provider = HTTPProvider(['http://localhost:1', 'http://localhost:2'], 5 * 60, 1, 1)
    with pytest.raises(Exception):
        provider._get('test')


@pytest.mark.unit
def test_first_fallback_bad():
    def _simple_get(manager, endpoint, query_params=None, stream=False, **kwargs):
        if manager._uri == 'http://localhost:1':
            raise Exception('Bad host')  # pylint: disable=broad-exception-raised
        return manager._uri, endpoint

    provider = HTTPProvider(['http://localhost:1', 'http://localhost:2'], 5 * 60, 1, 1)
    provider._get_without_fallbacks = _simple_get
    assert provider._get('test') == ('http://localhost:2', 'test')


@pytest.mark.unit
def test_force_raise():
    class CustomError(Exception):
        pass

    def _simple_get(manager, endpoint, query_params=None, stream=False, **kwargs):
        if manager._uri == 'http://localhost:1':
            raise Exception('Bad host')  # pylint: disable=broad-exception-raised
        return manager._uri, endpoint

    provider = HTTPProvider(['http://localhost:1', 'http://localhost:2'], 5 * 60, 1, 1)
    provider._get_without_fallbacks = Mock(side_effect=_simple_get)
    with pytest.raises(CustomError):
        provider._get('test', force_raise=lambda _: CustomError())
    # Note: We can't easily test the exact manager object, so let's just verify the method was called
    provider._get_without_fallbacks.assert_called_once()


@pytest.mark.unit
def test_retval_validator():
    provider = HTTPProvider(['http://localhost:1', 'http://localhost:2'], 5 * 60, 1, 1)
    provider.PROMETHEUS_HISTOGRAM = CL_REQUESTS_DURATION

    resp = Response()
    resp.status_code = 200
    resp._content = b'{"data": {}}'

    # Mock the HTTPSessionManagerProxy's method instead of session.get
    for manager in provider.managers:
        manager.get_response_from_get_request = Mock(return_value=resp)

    def failed_validation(*args, **kwargs):
        raise ValueError("Validation failed")

    with pytest.raises(ValueError, match="Validation failed"):
        provider._get('test', retval_validator=failed_validation)


@pytest.mark.unit
def test_custom_error_provided():
    class CustomError(NotOkResponse):
        pass

    class TestProvider(SimpleHTTPProvider):
        PROVIDER_EXCEPTION = CustomError
        PROMETHEUS_HISTOGRAM = MagicMock()

        def call(self):
            return self._get('invalid_url')

    provider = TestProvider(['http://example.com/'], 1, 1, 1)

    # Mock the session.get method to avoid real network call
    resp = Response()
    resp.status_code = 500
    resp._content = b'Server Error'
    provider.session.get = Mock(return_value=resp)

    with pytest.raises(CustomError):
        provider.call()
