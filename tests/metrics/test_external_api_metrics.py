import logging
from unittest.mock import Mock

import pytest
import requests
import responses
from prometheus_client import REGISTRY

from src import variables
from src.providers.ipfs.cid import CID
from src.providers.ipfs.filebase import Filebase
from src.providers.ipfs.kubo import Kubo
from src.providers.ipfs.lido_ipfs import LidoIPFS
from src.providers.ipfs.pinata import Pinata
from src.providers.ipfs.types import FetchError
from src.utils.api.opsgenie import OpsGenieAPI


TEST_CID = CID("QmXvrr3gPtddcNrisH7i2nan9rY7v7RcxVQ9jjRreoWwRS")
MOCK_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
    "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)


def requests_count(service: str, method: str, code: int) -> float:
    value = REGISTRY.get_sample_value(
        f'{variables.PROMETHEUS_PREFIX}_external_api_requests_duration_count',
        {'service': service, 'method': method, 'code': str(code)},
    )
    return value or 0


@pytest.mark.unit
class TestProvidersRequestMetrics:
    @responses.activate
    def test_lido_ipfs_fetch__ok__request_counted(self):
        provider = LidoIPFS(host="https://ipfs-test.lido.fi", token="test_bearer_token", timeout=30)
        responses.add(responses.GET, f"https://ipfs-test.lido.fi/ipfs/{TEST_CID}", body=b"content", status=200)
        before = requests_count('LidoIPFS', 'GET', 200)

        provider._fetch(TEST_CID)

        assert requests_count('LidoIPFS', 'GET', 200) == before + 1

    @responses.activate
    def test_lido_ipfs_fetch__server_error__error_code_counted(self):
        provider = LidoIPFS(host="https://ipfs-test.lido.fi", token="test_bearer_token", timeout=30)
        responses.add(responses.GET, f"https://ipfs-test.lido.fi/ipfs/{TEST_CID}", status=500)
        before = requests_count('LidoIPFS', 'GET', 500)

        with pytest.raises(FetchError):
            provider._fetch(TEST_CID)

        assert requests_count('LidoIPFS', 'GET', 500) == before + 1

    @responses.activate
    def test_lido_ipfs_upload__ok__request_counted(self):
        provider = LidoIPFS(host="https://ipfs-test.lido.fi", token="test_bearer_token", timeout=30)
        responses.add(responses.POST, "https://ipfs-test.lido.fi/add", json={"cid": str(TEST_CID)}, status=200)
        before = requests_count('LidoIPFS', 'POST', 200)

        provider._upload(b"content")

        assert requests_count('LidoIPFS', 'POST', 200) == before + 1

    @responses.activate
    def test_pinata_fetch__dedicated_gateway_ok__request_counted(self):
        provider = Pinata(
            jwt_token=MOCK_JWT,
            timeout=30,
            dedicated_gateway_url="https://dedicated.gateway.com",
            dedicated_gateway_token="dedicated_token_123",
        )
        responses.add(responses.GET, f"https://dedicated.gateway.com/ipfs/{TEST_CID}", body=b"content", status=200)
        before = requests_count('Pinata', 'GET', 200)

        provider._fetch(TEST_CID)

        assert requests_count('Pinata', 'GET', 200) == before + 1

    @responses.activate
    def test_pinata_upload__ok__request_counted(self):
        provider = Pinata(
            jwt_token=MOCK_JWT,
            timeout=30,
            dedicated_gateway_url="https://dedicated.gateway.com",
            dedicated_gateway_token="dedicated_token_123",
        )
        responses.add(
            responses.POST, "https://api.pinata.cloud/pinning/pinFileToIPFS", json={"IpfsHash": str(TEST_CID)}
        )
        before = requests_count('Pinata', 'POST', 200)

        provider._upload(b"content")

        assert requests_count('Pinata', 'POST', 200) == before + 1

    @responses.activate
    def test_kubo_fetch__no_response__code_zero_counted(self):
        provider = Kubo(host="http://localhost", rpc_port=5001, timeout=30)
        responses.add(
            responses.POST, "http://localhost:5001/api/v0/cat", body=requests.ConnectionError("Network error")
        )
        before = requests_count('Kubo', 'POST', 0)

        with pytest.raises(FetchError):
            provider._fetch(TEST_CID)

        assert requests_count('Kubo', 'POST', 0) == before + 1

    @responses.activate
    def test_kubo_pin__ok__request_counted(self):
        provider = Kubo(host="http://localhost", rpc_port=5001, timeout=30)
        responses.add(responses.POST, "http://localhost:5001/api/v0/pin/add", json={"Pins": [str(TEST_CID)]})
        before = requests_count('Kubo', 'POST', 200)

        provider.pin(TEST_CID)

        assert requests_count('Kubo', 'POST', 200) == before + 1

    @responses.activate
    def test_filebase_upload__ok__counted_under_its_own_class_name(self):
        provider = Filebase(host="https://rpc.filebase.test", rpc_port=443, timeout=30, token="test_bearer_token")
        responses.add(responses.POST, "https://rpc.filebase.test:443/api/v0/add", json={"Hash": str(TEST_CID)})
        before = requests_count('Filebase', 'POST', 200)

        provider._upload(b"content")

        assert requests_count('Filebase', 'POST', 200) == before + 1

    @responses.activate
    def test_opsgenie_alert__ok__request_counted(self):
        opsgenie_api = OpsGenieAPI(
            api_key='test', api_url='https://api.testopsgenie.com', logger=Mock(spec=logging.Logger)
        )
        responses.post('https://api.testopsgenie.com/v2/alerts', status=200)
        before = requests_count('OpsGenieAPI', 'POST', 200)

        opsgenie_api.send_opsgenie_alert({})

        assert requests_count('OpsGenieAPI', 'POST', 200) == before + 1
