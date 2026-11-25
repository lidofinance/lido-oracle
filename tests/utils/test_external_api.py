from unittest.mock import Mock

import pytest
import requests
from prometheus_client import REGISTRY

from src import variables
from src.utils.external_api import observe_external_api_request


def requests_count(service: str, method: str, code: int) -> float:
    value = REGISTRY.get_sample_value(
        f'{variables.PROMETHEUS_PREFIX}_external_api_requests_duration_count',
        {'service': service, 'method': method, 'code': str(code)},
    )
    return value or 0


@pytest.mark.unit
class TestObserveExternalApiRequest:
    def test_observe_external_api_request__response__returns_it_and_counts_status_code(self):
        response = Mock(spec=requests.Response, status_code=201)
        send = Mock(return_value=response)
        before = requests_count('test_service', 'GET', 201)

        result = observe_external_api_request('test_service', 'GET', send, 'http://url', timeout=1)

        assert result is response
        send.assert_called_once_with('http://url', timeout=1)
        assert requests_count('test_service', 'GET', 201) == before + 1

    def test_observe_external_api_request__no_response__reraises_and_counts_code_zero(self):
        send = Mock(side_effect=requests.ConnectionError('Network error'))
        before = requests_count('test_service', 'GET', 0)

        with pytest.raises(requests.ConnectionError):
            observe_external_api_request('test_service', 'GET', send, 'http://url')

        assert requests_count('test_service', 'GET', 0) == before + 1

    def test_observe_external_api_request__process_interrupted__original_exception_and_code_zero(self):
        send = Mock(side_effect=KeyboardInterrupt)
        before = requests_count('test_service', 'GET', 0)

        with pytest.raises(KeyboardInterrupt):
            observe_external_api_request('test_service', 'GET', send, 'http://url')

        assert requests_count('test_service', 'GET', 0) == before + 1
