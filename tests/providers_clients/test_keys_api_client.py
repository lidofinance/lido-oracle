"""Simple tests for the keys api client responses validity."""

from unittest.mock import Mock

import pytest
from web3 import Web3

import src.providers.keys.client as keys_api_client_module
from src import variables
from src.providers.keys.client import KeysAPIClient, KeysOutdatedException
from src.variables import KEYS_API_URI
from tests.factory.blockstamp import ReferenceBlockStampFactory


@pytest.fixture()
def keys_api_client():
    return KeysAPIClient(KEYS_API_URI, 5 * 60, 5, 5)


empty_blockstamp = ReferenceBlockStampFactory.build(block_number=0)


@pytest.mark.integration
def test_get_used_lido_keys(keys_api_client):
    lido_keys = keys_api_client.get_used_lido_keys(empty_blockstamp)
    for lido_key in lido_keys:
        assert lido_key.used
    assert lido_keys


@pytest.mark.integration
def test_get_used_module_operators_keys__csm_module(keys_api_client: KeysAPIClient):
    csm_module_operators_keys = keys_api_client.get_used_module_operators_keys(
        module_address=variables.CSM_MODULE_ADDRESS,  # type: ignore
        blockstamp=empty_blockstamp,
    )

    assert csm_module_operators_keys['module']['stakingModuleAddress'] == variables.CSM_MODULE_ADDRESS
    assert csm_module_operators_keys['module']['id'] >= 0
    assert len(csm_module_operators_keys['keys']) > 0
    assert len(csm_module_operators_keys['operators']) > 0
    for lido_key in csm_module_operators_keys['keys']:
        assert lido_key.used
        assert lido_key.operatorIndex >= 0
        assert Web3.is_address(lido_key.moduleAddress)
    for operator in csm_module_operators_keys['operators']:
        assert operator['index'] >= 0
        assert operator['moduleAddress'] == variables.CSM_MODULE_ADDRESS


@pytest.mark.integration
def test_get_status(keys_api_client):
    status = keys_api_client.get_status()
    assert status


@pytest.mark.unit
def test_get_with_blockstamp_retries_exhausted(keys_api_client, monkeypatch):
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

    assert sleep_mock.call_count == variables.HTTP_REQUEST_RETRY_COUNT_KEYS_API - 1
    sleep_mock.assert_called_with(variables.HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_KEYS_API)
