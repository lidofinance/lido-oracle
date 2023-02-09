import pytest

from src.providers.keys.client import KeysAPIClient
from src.providers.keys.typings import LidoKey, OperatorResponse
from src.variables import KEYS_API_URI

pytestmarks = pytest.mark.integration


@pytest.fixture()
def keys_api_client():
    return KeysAPIClient(KEYS_API_URI)


def test_get_all_lido_keys(keys_api_client):
    lido_keys = keys_api_client.get_all_lido_keys({'block_number': 0})
    assert lido_keys
    assert LidoKey.__required_keys__ == lido_keys[0].keys()


def test_get_operators(keys_api_client):
    operators = keys_api_client.get_operators({'block_number': 0})
    assert operators
    assert OperatorResponse.__required_keys__ == operators[0].keys()
