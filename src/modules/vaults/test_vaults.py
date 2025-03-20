# test_my_class.py

import json
import os
from web3 import Web3

from src.main import ipfs_providers
from src.modules.vaults.vaults import Vaults, get_vaults_valuation, get_merkle_tree
from src.providers.consensus.client import ConsensusClient
from src.providers.ipfs import MultiIPFSProvider
from src.types import BlockRoot, SlotNumber
from src.utils.blockstamp import build_blockstamp

EXECUTION_CLIENT_URI =  os.getenv('EXECUTION_CLIENT_URI', '')
CONSENSUS_CLIENT_URI = os.getenv('CONSENSUS_CLIENT_URI')
PINATA_JWT = os.getenv('PINATA_JWT')

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

        self.ipfs_client = MultiIPFSProvider(ipfs_providers(), retries=3)

        vault_hub_runner = w3.eth.contract(abi=abi, address=self.vault_hub_address)
        self.vaults = Vaults(vault_hub_runner.functions, self.cc, w3, self.ipfs_client)

    def test_valuation(self):
        got = self.vaults.get_vault_addresses()
        print(got)
        assert len(got) == 2

    def test_cl_client(self):
        block_root = BlockRoot(self.cc.get_block_root('finalized').root)

        slot_number = 7227648
        block_details = self.cc.get_block_details(SlotNumber(slot_number))

        bs = build_blockstamp(block_details)

        vaults_to_balance = self.vaults.get_vault_addresses()
        vaults_to_validators = self.vaults.get_validators(bs, vaults_to_balance)

        vaults_valuation = get_vaults_valuation(vaults_to_balance, vaults_to_validators)

        merkle_tree = get_merkle_tree(vaults_valuation)
        got = f"0x{merkle_tree.root.hex()}"
        expected = '0x62e46ef2b3ed866d2dba4a55f4a58dfa49e976e958ca5cfa357b3bb7ae553a2f'
        assert got == expected

        def encoder(o):
            if isinstance(o, bytes):
                return f"0x{o.hex()}"
            raise TypeError(f"Object of type {type(o)} is not JSON serializable")

        dumped_tree = merkle_tree.dump()
        dumped_tree.update({
            "merkle_tree_root": got,
            "ref_slof": bs.slot_number
        })

        dumped_tree_str = json.dumps(dumped_tree, default=encoder)
        print(dumped_tree_str)

        # vault_proofs = get_vault_to_proof_map(merkle_tree, vaults_to_balance, vaults_to_validators)
        # print(vault_proofs)

    def test_handle(self):
        slot_number = 7227648
        block_details = self.cc.get_block_details(SlotNumber(slot_number))

        bs = build_blockstamp(block_details)
        self.vaults.handle(bs)