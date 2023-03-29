# pylint: disable=protected-access
import pytest

from src.providers.http_provider import HTTPProvider, NoActiveProviderError


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


def test_all_fallbacks_ok():
    provider = HTTPProvider(['http://localhost:1', 'http://localhost:2'])
    provider._get_without_fallbacks = lambda host, endpoint, path_params, query_params: (host, endpoint)
    assert provider._get('test') == ('http://localhost:1', 'test')


def test_all_fallbacks_bad():
    provider = HTTPProvider(['http://localhost:1', 'http://localhost:2'])
    with pytest.raises(NoActiveProviderError):
        provider._get('test')


def test_first_fallback_bad():
    def _simple_get(host, endpoint, *_):
        if host == 'http://localhost:1':
            raise Exception('Bad host')  # pylint: disable=broad-exception-raised
        return host, endpoint

    provider = HTTPProvider(['http://localhost:1', 'http://localhost:2'])
    provider._get_without_fallbacks = _simple_get
    assert provider._get('test') == ('http://localhost:2', 'test')
