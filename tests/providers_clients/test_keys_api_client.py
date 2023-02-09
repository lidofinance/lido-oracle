"""Simple tests for the keys api client responses validity."""
import pytest

from src.providers.keys.client import KeysAPIClient
from src.typings import BlockStamp
from src.variables import KEYS_API_URI

pytestmarks = pytest.mark.integration


@pytest.fixture()
def keys_api_client():
    return KeysAPIClient(KEYS_API_URI)


empty_blockstamp = BlockStamp(
        block_root=None,
        state_root=None,
        slot_number='',
        block_hash='',
        block_number=0
    )


def test_get_all_lido_keys(keys_api_client):
    lido_keys = keys_api_client.get_all_lido_keys(empty_blockstamp)
    assert lido_keys


def test_get_operators(keys_api_client):
    operators = keys_api_client.get_operators(empty_blockstamp)
    assert operators
