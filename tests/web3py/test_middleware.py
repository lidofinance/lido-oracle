from unittest.mock import call, Mock, patch, mock_open, MagicMock, ANY

import pytest
from requests import HTTPError
from web3 import Web3, HTTPProvider
from web3_multi_provider import NoActiveProviderError

from src.metrics.prometheus.basic import EL_REQUESTS_DURATION
from src.variables import EXECUTION_CLIENT_URI
from src.web3py.middleware import add_requests_metric_middleware, Web3MetricsMiddleware

pytestmark = pytest.mark.integration


@pytest.fixture()
def provider():
    return HTTPProvider(EXECUTION_CLIENT_URI[0])


@pytest.fixture()
def web3(provider):
    web3 = Web3(provider)
    add_requests_metric_middleware(web3)
    return web3


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


@pytest.mark.integration
def test_success(web3):
    web3.eth.get_block_number()
    labels = _get_requests_labels()
    assert labels == {
        'call_method': '',
        'call_to': '',
        'code': '0',
        'endpoint': 'eth_blockNumber',
        'le': '0.01',
    }


@pytest.mark.integration
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


@pytest.mark.unit
class TestMetricsCollectorUnit:
    @pytest.fixture
    def mock_web3(self):
        """Mock Web3 instance."""
        mock_w3 = MagicMock(spec=Web3)
        mock_w3.provider = MagicMock()
        mock_w3.eth = Mock()
        mock_w3.provider.endpoint_uri = 'http://localhost:8545'
        return mock_w3

    @pytest.fixture
    def mock_make_request(self):
        """Mock for make_request callable."""
        return Mock()

    @pytest.fixture
    def mock_metrics_duration(self):
        """Mock for EL_REQUESTS_DURATION.histogram."""
        with patch('src.web3py.middleware.EL_REQUESTS_DURATION') as mock_histogram:
            mock_histogram.time.return_value.__enter__ = Mock(return_value=mock_histogram)
            mock_histogram.time.return_value.__exit__ = Mock(return_value=False)
            yield mock_histogram

    @pytest.fixture
    def load_abi_files(self):
        """Helper function to simulate loading ABI files from the assets directory."""
        assets_dir = './assets/'
        test_abi = '{"abi": [{"type": "function", "name": "testFunction", "inputs": []}]}'

        with patch('os.listdir') as mock_listdir, patch('builtins.open', mock_open(read_data=test_abi)):
            mock_listdir.return_value = ['test_contract.json']
            yield

    def test_metrics_collector_eth_call(self, mock_web3, mock_make_request, mock_metrics_duration, load_abi_files):
        """
        Test the metrics collector for an `eth_call` method.
        """
        web3_metrics_middleware = Web3MetricsMiddleware(mock_web3)
        middleware = web3_metrics_middleware.wrap_make_request(mock_make_request)

        method = 'eth_call'
        params = [{'to': '0x1234567890abcdef', 'data': '0xabcdef'}]
        mock_make_request.return_value = {'result': 'success'}

        response = middleware(method, params)

        assert response == {'result': 'success'}
        mock_make_request.assert_called_once_with(method, params)
        assert mock_metrics_duration.time.called
        assert mock_metrics_duration.labels.called
        assert mock_metrics_duration.labels.call_args == call(
            endpoint=method,
            call_method=ANY,
            call_to='0x1234567890abcdef',
            code=0,
            domain='localhost:8545',
        )

    def test_metrics_collector_eth_getBalance(
        self, mock_web3, mock_make_request, mock_metrics_duration, load_abi_files
    ):
        """
        Test the metrics collector for an `eth_getBalance` method.
        """
        web3_metrics_middleware = Web3MetricsMiddleware(mock_web3)
        middleware = web3_metrics_middleware.wrap_make_request(mock_make_request)

        method = 'eth_getBalance'
        params = ['0x1234567890abcdef', 'latest']
        mock_make_request.return_value = {'result': '1000'}

        response = middleware(method, params)

        assert response == {'result': '1000'}
        mock_make_request.assert_called_once_with(method, params)
        assert mock_metrics_duration.time.called
        assert mock_metrics_duration.labels.called
        assert mock_metrics_duration.labels.call_args == call(
            endpoint=method,
            call_method=ANY,
            call_to='0x1234567890abcdef',
            code=0,
            domain='localhost:8545',
        )

    def test_metrics_collector_handle_no_provider(self, mock_web3, mock_make_request, mock_metrics_duration):
        """
        Test that the metrics collector handles the NoActiveProviderError.
        """
        web3_metrics_middleware = Web3MetricsMiddleware(mock_web3)
        middleware = web3_metrics_middleware.wrap_make_request(mock_make_request)

        method = 'eth_call'
        params = [{'to': '0x1234567890abcdef', 'data': '0xabcdef'}]
        mock_make_request.side_effect = NoActiveProviderError

        with pytest.raises(NoActiveProviderError):
            middleware(method, params)

        assert mock_metrics_duration.labels.called
        assert mock_metrics_duration.labels.call_args == call(
            endpoint=method,
            call_method=ANY,
            call_to='0x1234567890abcdef',
            code=None,
            domain='localhost:8545',
        )

    def test_metrics_collector_handle_http_error(self, mock_web3, mock_make_request, mock_metrics_duration):
        """
        Test that the metrics collector handles HTTPError correctly.
        """
        web3_metrics_middleware = Web3MetricsMiddleware(mock_web3)
        middleware = web3_metrics_middleware.wrap_make_request(mock_make_request)

        method = 'eth_call'
        params = [{'to': '0x1234567890abcdef', 'data': '0xabcdef'}]
        mock_response = Mock(status_code=500)
        mock_http_error = HTTPError(response=mock_response)
        mock_make_request.side_effect = mock_http_error

        with pytest.raises(HTTPError):
            middleware(method, params)

        assert mock_metrics_duration.labels.called
        assert mock_metrics_duration.labels.call_args == call(
            endpoint=method,
            call_method=ANY,
            call_to='0x1234567890abcdef',
            code=500,
            domain='localhost:8545',
        )
