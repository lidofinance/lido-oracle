import pytest
from requests import HTTPError
from web3 import Web3, HTTPProvider

from src.metrics.prometheus.basic import ETH1_RPC_REQUESTS
from src.variables import EXECUTION_CLIENT_URI
from src.web3_extentions import metrics_collector


@pytest.fixture()
def provider():
    return HTTPProvider(EXECUTION_CLIENT_URI[0])


@pytest.fixture()
def web3(provider):
    return Web3(provider, middlewares=[metrics_collector])


@pytest.fixture(autouse=True)
def clear_metrics():
    yield
    ETH1_RPC_REQUESTS.clear()


def _get_requests_labels():
    samples = ETH1_RPC_REQUESTS.collect()[0].samples
    assert samples
    labels = samples[0].labels
    # We do not check domain because it is different for each provider
    labels.pop('domain')
    return labels


def test_success(provider, web3):
    web3.eth.get_block_number()
    labels = _get_requests_labels()
    assert labels == {'method': 'eth_blockNumber', 'code': '0'}


def test_fail_with_status_code(provider, web3):
    provider.endpoint_uri = 'https://github.com'
    with pytest.raises(HTTPError):
        web3.eth.get_block_number()
    labels = _get_requests_labels()
    assert labels == {'method': 'eth_blockNumber', 'code': '404'}


def test_fail_with_body_error(provider, web3):
    with pytest.raises(ValueError):
        web3.eth.get_coinbase()
    labels = _get_requests_labels()
    assert labels == {'method': 'eth_coinbase', 'code': '-32000'}
