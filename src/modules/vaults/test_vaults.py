# test_my_class.py

import unittest

from web3 import Web3

from src.modules.vaults.vaults import Vaults, ClClient
import json
from src.providers.consensus.client import ConsensusClient
from src.types import BlockRoot
from src.utils.blockstamp import build_blockstamp

import os

EXECUTION_CLIENT_URI =  os.getenv('EXECUTION_CLIENT_URI', '')
CONSENSUS_CLIENT_URI = os.getenv('CONSENSUS_CLIENT_URI')

class TestVaults(unittest.TestCase):

    vault_hub_address = '0x33532749B2e74CE7e4e222a70Df89b7a1523AF67'

    def setUp(self):
        current_dir = os.path.dirname(__file__)
        project_root = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
        abi_path = os.path.join(project_root, 'assets', 'VaultHub.json')

        with open(abi_path, 'r', encoding='utf-8') as f:
            abi = json.load(f)

        w3 = Web3(Web3.HTTPProvider(EXECUTION_CLIENT_URI))

        self.cc = ConsensusClient(hosts=[CONSENSUS_CLIENT_URI], request_timeout=5 * 60, retry_total=1,
                                  retry_backoff_factor=1)

        vault_hub_runner = w3.eth.contract(abi=abi, address=self.vault_hub_address)
        self.vaults = Vaults(vault_hub_runner.functions, self.cc)

    def test_valuation(self):
        got = self.vaults.get_valuation()
        self.assertEqual(got, 0)

    def test_cl_client(self):
        block_root = BlockRoot(self.cc.get_block_root('finalized').root)
        block_details = self.cc.get_block_details(block_root)
        bs = build_blockstamp(block_details)
        print(bs)

        got = self.vaults.get_validators(bs)
        expected = 1
        self.assertEqual(got, expected)

if __name__ == "__main__":
    unittest.main()
