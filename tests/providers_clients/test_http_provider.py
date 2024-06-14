# pylint: disable=protected-access
from unittest.mock import Mock

import pytest

from src.providers.http_provider import HTTPProvider, NoHostsProvided


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


def test_no_providers():
    with pytest.raises(NoHostsProvided):
        HTTPProvider([], 5 * 60, 1, 1)


def test_all_fallbacks_ok():
    provider = HTTPProvider(['http://localhost:1', 'http://localhost:2'], 5 * 60, 1, 1)
    provider._get_without_fallbacks = lambda host, endpoint, path_params, query_params, stream: (host, endpoint)
    assert provider._get('test') == ('http://localhost:1', 'test')
    assert len(provider.get_all_providers()) == 2


def test_all_fallbacks_bad():
    provider = HTTPProvider(['http://localhost:1', 'http://localhost:2'], 5 * 60, 1, 1)
    with pytest.raises(Exception):
        provider._get('test')


def test_first_fallback_bad():
    def _simple_get(host, endpoint, *_):
        if host == 'http://localhost:1':
            raise Exception('Bad host')  # pylint: disable=broad-exception-raised
        return host, endpoint

    provider = HTTPProvider(['http://localhost:1', 'http://localhost:2'], 5 * 60, 1, 1)
    provider._get_without_fallbacks = _simple_get
    assert provider._get('test') == ('http://localhost:2', 'test')


def test_force_raise():
    class CustomError(Exception):
        pass

    def _simple_get(host, endpoint, *_):
        if host == 'http://localhost:1':
            raise Exception('Bad host')  # pylint: disable=broad-exception-raised
        return host, endpoint

    provider = HTTPProvider(['http://localhost:1', 'http://localhost:2'], 5 * 60, 1, 1)
    provider._get_without_fallbacks = Mock(side_effect=_simple_get)
    with pytest.raises(CustomError):
        provider._get('test', force_raise=lambda _: CustomError())
    provider._get_without_fallbacks.assert_called_once_with('http://localhost:1', 'test', None, None, False)
