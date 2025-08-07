import re
from typing import cast
from unittest import mock

import pytest
import responses
from eth_typing import HexStr
from packaging.version import Version
from web3 import Web3

import src.providers.keys.client as keys_api_client_module
from src import constants, variables
from src.providers.keys.client import KAPIClientError, KAPIInconsistentData, KeysAPIClient, KeysOutdatedException
from src.providers.keys.types import LidoKey
from src.types import StakingModuleAddress
from tests.factory.blockstamp import ReferenceBlockStampFactory


@pytest.mark.integration
@pytest.mark.mainnet
class TestIntegrationKeysAPIClient:
    # https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#bls-signatures
    BLS_PUBLIC_KEY_SIZE = 48
    BLS_SIGNATURE_SIZE = 96
    BLS_PUBLIC_KEY_PATTERN = re.compile(r'^0x[0-9a-fA-F]{96}$')
    BLS_SIGNATURE_PATTERN = re.compile(r'^0x[0-9a-fA-F]{192}$')

    def _is_valid_hex_format(self, value: HexStr, pattern: re.Pattern, expected_bytes: int) -> bool:
        if not isinstance(value, str) or pattern.match(value) is None:
            return False
        try:
            bytes_value = Web3.to_bytes(hexstr=value)
            return len(bytes_value) == expected_bytes
        except ValueError:
            return False

    def _is_valid_bls_public_key(self, value: HexStr) -> bool:
        return self._is_valid_hex_format(value, self.BLS_PUBLIC_KEY_PATTERN, self.BLS_PUBLIC_KEY_SIZE)

    def _is_valid_bls_signature(self, value: HexStr) -> bool:
        return self._is_valid_hex_format(value, self.BLS_SIGNATURE_PATTERN, self.BLS_SIGNATURE_SIZE)

    def _assert_lido_key(self, lido_key: LidoKey):
        assert lido_key.operatorIndex >= 0
        assert Web3.is_address(lido_key.moduleAddress)
        assert self._is_valid_bls_public_key(lido_key.key)
        assert self._is_valid_bls_signature(lido_key.depositSignature)

    @pytest.fixture
    def keys_api_client(self):
        return KeysAPIClient(
            hosts=variables.KEYS_API_URI,
            request_timeout=5 * 60,
            retry_total=5,
            retry_backoff_factor=2,
        )

    @pytest.fixture
    def empty_blockstamp(self):
        return ReferenceBlockStampFactory.build(block_number=0)

    def test_get_used_lido_keys__all_used_keys__response_data_is_valid(
        self,
        keys_api_client: KeysAPIClient,
        empty_blockstamp,
    ):
        keys = keys_api_client.get_used_lido_keys(empty_blockstamp)

        assert len(keys) > 0
        keys_seen: list[str] = []
        for lido_key in keys:
            assert lido_key.used
            self._assert_lido_key(lido_key)
            assert lido_key.key not in keys_seen
            keys_seen.append(lido_key.key)

    def test_get_used_module_operators_keys__csm_module__response_data_is_valid(
        self,
        keys_api_client: KeysAPIClient,
        empty_blockstamp,
    ):
        csm_module_operators_keys = keys_api_client.get_used_module_operators_keys(
            module_address=variables.CSM_MODULE_ADDRESS,  # type: ignore
            blockstamp=empty_blockstamp,
        )

        assert csm_module_operators_keys['module']['stakingModuleAddress'] == variables.CSM_MODULE_ADDRESS
        assert csm_module_operators_keys['module']['id'] >= 0
        assert len(csm_module_operators_keys['keys']) > 0
        assert len(csm_module_operators_keys['operators']) > 0
        keys_seen: list[str] = []
        for lido_key in csm_module_operators_keys['keys']:
            assert lido_key.used
            self._assert_lido_key(lido_key)
            assert lido_key.key not in keys_seen
            keys_seen.append(lido_key.key)
        for operator in csm_module_operators_keys['operators']:
            assert operator['index'] >= 0
            assert Web3.is_address(operator['rewardAddress'])
            assert operator['moduleAddress'] == variables.CSM_MODULE_ADDRESS

    def test_get_status__response_version_is_allowed(
        self,
        keys_api_client: KeysAPIClient,
    ):
        status = keys_api_client.get_status()

        assert Version(status.appVersion) >= constants.ALLOWED_KAPI_VERSION
        assert status.chainId == 1

    def test_check_providers_consistency__mainnet(self, keys_api_client):
        chain_id = keys_api_client.check_providers_consistency()

        assert chain_id == 1


@pytest.mark.unit
class TestUnitKeysAPIClient:
    KEYS_API_MOCK_URL = 'http://mock:1234/'

    @pytest.fixture()
    def keys_api_client(self):
        return KeysAPIClient(
            hosts=[self.KEYS_API_MOCK_URL],
            request_timeout=5 * 60,
            retry_total=5,
            retry_backoff_factor=2,
        )

    @pytest.fixture()
    def empty_blockstamp(self):
        return ReferenceBlockStampFactory.build(block_number=0)

    @responses.activate
    def test_get_used_lido_keys__empty_response__empty_list(
        self,
        keys_api_client: KeysAPIClient,
        empty_blockstamp,
    ):
        responses.get(
            self.KEYS_API_MOCK_URL + keys_api_client.USED_KEYS,
            json={
                'data': [],
                'meta': {
                    'elBlockSnapshot': {
                        'blockNumber': 0,
                        'blockHash': 'string',
                        'timestamp': 0,
                        'lastChangedBlockHash': 'string',
                    }
                },
            },
        )

        keys = keys_api_client.get_used_lido_keys(empty_blockstamp)

        assert len(keys) == 0

    @responses.activate
    def test_get_used_lido_keys__outdated_block__raises_keys_outdated_exception(
        self,
        keys_api_client: KeysAPIClient,
        empty_blockstamp,
        monkeypatch,
    ):
        responses.get(
            self.KEYS_API_MOCK_URL + keys_api_client.USED_KEYS,
            json={
                'data': [],
                'meta': {
                    'elBlockSnapshot': {
                        'blockNumber': -1,
                        'blockHash': 'string',
                        'timestamp': 0,
                        'lastChangedBlockHash': 'string',
                    }
                },
            },
        )
        sleep_mock = mock.Mock()

        with monkeypatch.context() as m, pytest.raises(KeysOutdatedException):
            m.setattr(keys_api_client_module, 'sleep', sleep_mock)
            keys_api_client.get_used_lido_keys(empty_blockstamp)

        assert sleep_mock.call_count == keys_api_client.retry_count - 1

    @responses.activate
    def test_get_used_lido_keys__server_error__raises_kapi_client_error(
        self,
        keys_api_client: KeysAPIClient,
        empty_blockstamp,
    ):
        responses.get(
            self.KEYS_API_MOCK_URL + keys_api_client.USED_KEYS, status=500, json={'error': 'Internal Server Error'}
        )

        with pytest.raises(KAPIClientError):
            keys_api_client.get_used_lido_keys(empty_blockstamp)

    @responses.activate
    def test_get_used_lido_keys__two_calls__one_http_request_cached(
        self,
        keys_api_client: KeysAPIClient,
        empty_blockstamp,
    ):
        responses.get(
            self.KEYS_API_MOCK_URL + keys_api_client.USED_KEYS,
            json={
                'data': [{'key': '', 'used': True, 'operatorIndex': 0, 'moduleAddress': '', 'depositSignature': ''}],
                'meta': {'elBlockSnapshot': {'blockNumber': 0}},
            },
        )

        keys1 = keys_api_client.get_used_lido_keys(empty_blockstamp)
        keys2 = keys_api_client.get_used_lido_keys(empty_blockstamp)

        assert keys1 == keys2
        assert len(responses.calls) == 1

    @responses.activate
    def test_get_used_module_operators_keys__empty_response__empty_lists(
        self,
        keys_api_client: KeysAPIClient,
        empty_blockstamp,
    ):
        module_address = cast(StakingModuleAddress, '0xdtestest')
        responses.get(
            self.KEYS_API_MOCK_URL + keys_api_client.USED_MODULE_OPERATORS_KEYS.format(module_address),
            json={
                'data': {'keys': [], 'module': {'stakingModuleAddress': str(module_address), 'id': 1}, 'operators': []},
                'meta': {
                    'elBlockSnapshot': {
                        'blockNumber': 0,
                        'blockHash': 'string',
                        'timestamp': 0,
                        'lastChangedBlockHash': 'string',
                    }
                },
            },
        )

        result = keys_api_client.get_used_module_operators_keys(module_address, empty_blockstamp)

        assert len(result['keys']) == 0
        assert len(result['operators']) == 0

    @responses.activate
    def test_get_used_module_operators_keys__outdated_block__raises_keys_outdated_exception(
        self,
        keys_api_client: KeysAPIClient,
        empty_blockstamp,
        monkeypatch,
    ):
        module_address = cast(StakingModuleAddress, '0xdtestest')
        responses.get(
            self.KEYS_API_MOCK_URL + keys_api_client.USED_MODULE_OPERATORS_KEYS.format(module_address),
            json={
                'data': {'keys': [], 'module': {'stakingModuleAddress': str(module_address), 'id': 1}, 'operators': []},
                'meta': {
                    'elBlockSnapshot': {
                        'blockNumber': -1,
                        'blockHash': 'string',
                        'timestamp': 0,
                        'lastChangedBlockHash': 'string',
                    }
                },
            },
        )
        sleep_mock = mock.Mock()

        with monkeypatch.context() as m, pytest.raises(KeysOutdatedException):
            m.setattr(keys_api_client_module, 'sleep', sleep_mock)
            keys_api_client.get_used_module_operators_keys(module_address, empty_blockstamp)

        assert sleep_mock.call_count == keys_api_client.retry_count - 1

    @responses.activate
    def test_get_used_lido_keys__used_False__raises_inconsistent_data_error(
        self,
        keys_api_client: KeysAPIClient,
        empty_blockstamp,
    ):
        responses.get(
            self.KEYS_API_MOCK_URL + keys_api_client.USED_KEYS,
            json={
                'data': [{'key': '', 'used': False, 'operatorIndex': 0, 'moduleAddress': '', 'depositSignature': ''}],
                'meta': {'elBlockSnapshot': {'blockNumber': 0}},
            },
        )

        with pytest.raises(KAPIInconsistentData, match="unused"):
            keys_api_client.get_used_lido_keys(empty_blockstamp)

    @responses.activate
    def test_get_used_lido_keys__duplicates__raises_inconsistent_data_error(
        self,
        keys_api_client: KeysAPIClient,
        empty_blockstamp,
    ):
        responses.get(
            self.KEYS_API_MOCK_URL + keys_api_client.USED_KEYS,
            json={
                'data': [
                    {
                        'key': '',
                        'used': True,
                        'operatorIndex': 0,
                        'moduleAddress': '',
                        'depositSignature': '',
                    }
                ]
                * 2,
                'meta': {'elBlockSnapshot': {'blockNumber': 0}},
            },
        )

        with pytest.raises(KAPIInconsistentData, match="duplicated"):
            keys_api_client.get_used_lido_keys(empty_blockstamp)

    @responses.activate
    def test_get_used_module_operators_keys__server_error__raises_kapi_client_error(
        self,
        keys_api_client: KeysAPIClient,
        empty_blockstamp,
    ):
        module_address = cast(StakingModuleAddress, '0xdtestest')
        responses.get(
            self.KEYS_API_MOCK_URL + keys_api_client.USED_MODULE_OPERATORS_KEYS.format(module_address),
            status=500,
            json={'error': 'Internal Server Error'},
        )

        with pytest.raises(KAPIClientError):
            keys_api_client.get_used_module_operators_keys(module_address, empty_blockstamp)

    @responses.activate
    def test_get_used_module_operators_keys__two_calls__one_http_request_cached(
        self,
        keys_api_client: KeysAPIClient,
        empty_blockstamp,
    ):
        module_address = cast(StakingModuleAddress, '0xdtestest')
        responses.get(
            self.KEYS_API_MOCK_URL + keys_api_client.USED_MODULE_OPERATORS_KEYS.format(module_address),
            json={
                'data': {
                    'keys': [
                        {
                            'key': '',
                            'used': True,
                            'operatorIndex': 0,
                            'moduleAddress': str(module_address),
                            'depositSignature': '',
                        }
                    ],
                    'module': {'stakingModuleAddress': str(module_address), 'id': 1},
                    'operators': [{'index': 0, 'rewardAddress': '0xabcdef', 'moduleAddress': str(module_address)}],
                },
                'meta': {'elBlockSnapshot': {'blockNumber': 0}},
            },
        )

        result1 = keys_api_client.get_used_module_operators_keys(module_address, empty_blockstamp)
        result2 = keys_api_client.get_used_module_operators_keys(module_address, empty_blockstamp)

        assert result1 == result2
        assert len(responses.calls) == 1

    @responses.activate
    def test_get_used_module_operators_keys__invalid_module__raises_inconsistent_data_error(
        self,
        keys_api_client: KeysAPIClient,
        empty_blockstamp,
    ):
        module_address = cast(StakingModuleAddress, '0xdtestest')
        responses.get(
            self.KEYS_API_MOCK_URL + keys_api_client.USED_MODULE_OPERATORS_KEYS.format(module_address),
            json={
                'data': {
                    'keys': [],
                    'module': {'stakingModuleAddress': 'SOME_OTHER_MODULE', 'id': 1},
                },
                'meta': {'elBlockSnapshot': {'blockNumber': 0}},
            },
        )

        with pytest.raises(KAPIInconsistentData, match="address mismatch"):
            keys_api_client.get_used_module_operators_keys(module_address, empty_blockstamp)

    @responses.activate
    def test_get_used_module_operators_keys__used_False__raises_inconsistent_data_error(
        self,
        keys_api_client: KeysAPIClient,
        empty_blockstamp,
    ):
        module_address = cast(StakingModuleAddress, '0xdtestest')
        responses.get(
            self.KEYS_API_MOCK_URL + keys_api_client.USED_MODULE_OPERATORS_KEYS.format(module_address),
            json={
                'data': {
                    'keys': [
                        {
                            'key': '',
                            'used': False,
                            'operatorIndex': 0,
                            'moduleAddress': str(module_address),
                            'depositSignature': '',
                        }
                    ],
                    'module': {'stakingModuleAddress': str(module_address), 'id': 1},
                },
                'meta': {'elBlockSnapshot': {'blockNumber': 0}},
            },
        )

        with pytest.raises(KAPIInconsistentData, match="unused"):
            keys_api_client.get_used_module_operators_keys(module_address, empty_blockstamp)

    @responses.activate
    def test_get_used_module_operators_keys__duplicates__raises_inconsistent_data_error(
        self,
        keys_api_client: KeysAPIClient,
        empty_blockstamp,
    ):
        module_address = cast(StakingModuleAddress, '0xdtestest')
        responses.get(
            self.KEYS_API_MOCK_URL + keys_api_client.USED_MODULE_OPERATORS_KEYS.format(module_address),
            json={
                'data': {
                    'keys': [
                        {
                            'key': '',
                            'used': True,
                            'operatorIndex': 0,
                            'moduleAddress': str(module_address),
                            'depositSignature': '',
                        }
                    ]
                    * 2,
                    'module': {'stakingModuleAddress': str(module_address), 'id': 1},
                },
                'meta': {'elBlockSnapshot': {'blockNumber': 0}},
            },
        )

        with pytest.raises(KAPIInconsistentData, match="duplicated"):
            keys_api_client.get_used_module_operators_keys(module_address, empty_blockstamp)
