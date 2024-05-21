import pytest
from requests import HTTPError
from web3 import Web3, HTTPProvider
from web3.exceptions import MethodUnavailable

from src.metrics.prometheus.basic import EL_REQUESTS_DURATION
from src.variables import EXECUTION_CLIENT_URI
from src.web3py.middleware import metrics_collector

pytestmark = pytest.mark.integration


@pytest.fixture()
def provider():
    return HTTPProvider(EXECUTION_CLIENT_URI[0])


@pytest.fixture()
def web3(provider):
    return Web3(provider, middlewares=[metrics_collector])


@pytest.fixture(autouse=True)
def clear_metrics():
    yield
    EL_REQUESTS_DURATION.clear()


def _get_requests_labels():
    samples = EL_REQUESTS_DURATION.collect()[0].samples
    assert samples
    labels = samples[0].labels
    # We do not check domain because it is different for each provider
    labels.pop('domain')
    return labels


def test_success(provider, web3):
    web3.eth.get_block_number()
    labels = _get_requests_labels()
    assert labels == {
        'call_method': '',
        'call_to': '',
        'code': '0',
        'endpoint': 'eth_blockNumber',
        'le': '0.01',
    }


def test_fail_with_status_code(provider, web3):
    provider.endpoint_uri = 'https://github.com'
    with pytest.raises(HTTPError):
        web3.eth.get_block_number()
    labels = _get_requests_labels()
    assert labels == {
        'call_method': '',
        'call_to': '',
        'code': '404',
        'endpoint': 'eth_blockNumber',
        'le': '0.01',
    }


def test_fail_with_body_error(provider, web3):
    with pytest.raises(MethodUnavailable):
        web3.eth.coinbase
    labels = _get_requests_labels()
    assert labels == {'call_method': '', 'call_to': '', 'code': '-32601', 'endpoint': 'eth_coinbase', 'le': '0.01'}
