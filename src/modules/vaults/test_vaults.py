# test_my_class.py

import json
import os

from web3 import Web3

from src.modules.vaults.vaults import Vaults, get_vaults_valuation, get_merkle_tree, get_vault_to_proof_map
from src.providers.consensus.client import ConsensusClient
from src.types import BlockRoot
from src.utils.blockstamp import build_blockstamp

EXECUTION_CLIENT_URI =  os.getenv('EXECUTION_CLIENT_URI', '')
CONSENSUS_CLIENT_URI = os.getenv('CONSENSUS_CLIENT_URI')

class TestVaults:

    vault_hub_address = '0x33532749B2e74CE7e4e222a70Df89b7a1523AF67'

    def setup_method(self):
        current_dir = os.path.dirname(__file__)
        project_root = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
        abi_path = os.path.join(project_root, 'assets', 'VaultHub.json')

        with open(abi_path, 'r', encoding='utf-8') as f:
            abi = json.load(f)

        w3 = Web3(Web3.HTTPProvider(EXECUTION_CLIENT_URI))

        self.cc = ConsensusClient(hosts=[CONSENSUS_CLIENT_URI], request_timeout=5 * 60, retry_total=1,
                                  retry_backoff_factor=1)

        vault_hub_runner = w3.eth.contract(abi=abi, address=self.vault_hub_address)
        self.vaults = Vaults(vault_hub_runner.functions, self.cc, w3)

    def test_valuation(self):
        got = self.vaults.get_vault_addresses()
        print(got)
        assert len(got) == 2

    def test_cl_client(self):
        block_root = BlockRoot(self.cc.get_block_root('finalized').root)
        block_details = self.cc.get_block_details(block_root)
        bs = build_blockstamp(block_details)

        vaults_to_balance = self.vaults.get_vault_addresses()
        vaults_to_validators = self.vaults.get_validators(bs, vaults_to_balance)

        vaults_valuation = get_vaults_valuation(vaults_to_balance, vaults_to_validators)

        merkle_tree = get_merkle_tree(vaults_valuation)
        got = f"0x{merkle_tree.root.hex()}"
        # expected = '0x97b0afa33d1c5af01d37d7bda17f90e4330b3c3a20976ea1eeb9b3cdf5330abd'
        # assert got == expected

        vault_proofs = get_vault_to_proof_map(merkle_tree, vaults_to_balance, vaults_to_validators)
        print(vault_proofs)
