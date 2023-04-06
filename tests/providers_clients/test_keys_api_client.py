"""Simple tests for the keys api client responses validity."""
from unittest.mock import Mock

import pytest

import src.providers.keys.client as keys_api_client_module
from src import variables
from src.providers.keys.client import KeysAPIClient, KeysOutdatedException
from src.variables import KEYS_API_URI
from tests.factory.blockstamp import ReferenceBlockStampFactory


@pytest.fixture()
def keys_api_client():
    return KeysAPIClient(KEYS_API_URI)


empty_blockstamp = ReferenceBlockStampFactory.build(block_number=0)


@pytest.mark.integration
def test_get_used_lido_keys(keys_api_client):
    lido_keys = keys_api_client.get_used_lido_keys(empty_blockstamp)
    assert lido_keys


@pytest.mark.integration
def test_get_status(keys_api_client):
    status = keys_api_client.get_status()
    assert status


@pytest.mark.unit
def test_get_with_blockstamp_retries_exhausted(keys_api_client, monkeypatch):
    variables.HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS = 1
    keys_api_client._get = Mock(
        return_value=(
            None,
            {"meta": {"elBlockSnapshot": {"blockNumber": empty_blockstamp.block_number - 1}}},
        )
    )

    sleep_mock = Mock()

    with pytest.raises(KeysOutdatedException):
        with monkeypatch.context() as m:
            m.setattr(keys_api_client_module, "sleep", sleep_mock)
            keys_api_client.get_used_lido_keys(empty_blockstamp)

    assert sleep_mock.call_count == variables.HTTP_REQUEST_RETRY_COUNT - 1
    sleep_mock.assert_called_with(variables.HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS)
