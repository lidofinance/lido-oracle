import pytest
import requests
from web3 import Web3

from src import variables
from src.providers.keys.onchain import OnchainKeysConfig, OnchainKeysFetcher
from src.types import BlockHash


# Community Staking Module, mainnet
CSM_ADDRESS = Web3.to_checksum_address('0xdA7dE2ECdDfccC6c3AF10108Db212ACBBf9EA83F')


@pytest.mark.integration
@pytest.mark.mainnet
class TestOnchainKeysMainnet:
    def test_fetch_modules_keys__csm__matches_keys_api(self, web3_integration):
        # Arrange: Keys API data is a snapshot of some block, read the module at that very block
        response = requests.get(
            f"{variables.KEYS_API_URI[0].rstrip('/')}/v1/modules/{CSM_ADDRESS}/keys?used=true", timeout=300
        ).json()
        block_hash = BlockHash(response['meta']['elBlockSnapshot']['blockHash'])
        kapi_keys = {
            (k['key'].lower(), k['depositSignature'].lower(), k['operatorIndex'], k['index'])
            for k in response['data']['keys']
        }
        fetcher = OnchainKeysFetcher(web3_integration, OnchainKeysConfig())

        # Act
        (module_keys,) = fetcher.fetch_modules_keys([CSM_ADDRESS], block_hash)

        # Assert
        onchain_keys = {(k.key, k.deposit_signature, k.operator_index, k.index) for k in module_keys.keys}
        assert onchain_keys == kapi_keys
