# test_my_class.py

import os

from web3 import Web3

from src.main import ipfs_providers
from src.providers.consensus.client import ConsensusClient
from src.providers.ipfs import MultiIPFSProvider
from src.types import BlockRoot, SlotNumber
from src.utils.blockstamp import build_blockstamp
from src.web3py.extensions import StakingVaults

EXECUTION_CLIENT_URI = os.getenv('EXECUTION_CLIENT_URI')
CONSENSUS_CLIENT_URI = os.getenv('CONSENSUS_CLIENT_URI')

class TestStakingVaults:

    abi_path = './../../../assets/'

    def setup_method(self):
        w3 = Web3(Web3.HTTPProvider(EXECUTION_CLIENT_URI))

        self.cc = ConsensusClient(hosts=[CONSENSUS_CLIENT_URI], request_timeout=5 * 60, retry_total=1,
                                  retry_backoff_factor=1)

        self.ipfs_client = MultiIPFSProvider(ipfs_providers(), retries=3)

        self.StakingVaults = StakingVaults(w3, self.ipfs_client,'./../../../assets/')

    def test_manual_vault_report(self):
        # block_root = BlockRoot(self.cc.get_block_root('finalized').root)
        slot_number = 7270944
        block_details = self.cc.get_block_details(SlotNumber(slot_number))

        bs = build_blockstamp(block_details)
        print(bs)

        validators = self.cc.get_validators_no_cache(bs)

        vaults_values, vaults_net_cash_flows, tree_data, vaults = self.StakingVaults.get_vaults_data(validators, bs)
        merkle_tree = self.StakingVaults.get_merkle_tree(tree_data)

        proof_cid = self.StakingVaults.publish_proofs(merkle_tree, bs, vaults)
        print(proof_cid)

        proof_tree = self.StakingVaults.publish_tree(merkle_tree, bs, proof_cid)
        print(proof_tree)

        got = f"0x{merkle_tree.root.hex()}"
        expected = '0x946f1d0dbf7dd495286dd9555bdeca50a68d78786131a38545d5375b03b860aa'
        assert got == expected
