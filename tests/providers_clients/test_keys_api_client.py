"""Simple tests for the keys api client responses validity."""
import pytest

from src.providers.keys.client import KeysAPIClient
from src.variables import KEYS_API_URI
from tests.factories import Factories

pytestmark = pytest.mark.integration


@pytest.fixture()
def keys_api_client():
    return KeysAPIClient(KEYS_API_URI)


empty_blockstamp = Factories.reference_blockstamp(block_number=0)


def test_get_all_lido_keys(keys_api_client):
    lido_keys = keys_api_client.get_all_lido_keys(empty_blockstamp)
    assert lido_keys

