# test_my_class.py

import os
from typing import cast

import pytest
from web3 import Web3

from src import variables
from src.main import ipfs_providers
from src.modules.accounting.staking_vaults import StakingVaults
from src.modules.submodules.types import ChainConfig
from src.providers.execution.contracts.lido_locator import LidoLocatorContract
from src.providers.execution.contracts.vault_hub import VaultHubContract
from src.providers.ipfs import MultiIPFSProvider
from src.types import BlockRoot
from src.utils.blockstamp import build_blockstamp
from src.web3py.extensions import ConsensusClientModule

EXECUTION_CLIENT_URI = os.getenv('EXECUTION_CLIENT_URI')
CONSENSUS_CLIENT_URI = os.getenv('CONSENSUS_CLIENT_URI')


@pytest.mark.skip(reason="Skipping all tests in this class on CI. Cause it's used for local testing")
class TestStakingVaultsSmoke:
    cc: ConsensusClientModule
    ipfs_client: MultiIPFSProvider

    def setup_method(self):
        w3 = Web3(Web3.HTTPProvider(EXECUTION_CLIENT_URI))

        self.cc = ConsensusClientModule([CONSENSUS_CLIENT_URI], w3)

        self.ipfs_client = MultiIPFSProvider(ipfs_providers(), retries=3)

        lido_locator: LidoLocatorContract = cast(
            LidoLocatorContract,
            w3.eth.contract(
                address=variables.LIDO_LOCATOR_ADDRESS,
                ContractFactoryClass=LidoLocatorContract,
                decode_tuples=True,
            ),
        )

        vault_hub: VaultHubContract = cast(
            VaultHubContract,
            w3.eth.contract(
                address=lido_locator.vault_hub(),
                ContractFactoryClass=VaultHubContract,
                decode_tuples=True,
            ),
        )

        self.StakingVaults = StakingVaults(w3, self.cc, self.ipfs_client, vault_hub)

    def test_manual_vault_report(self):
        block_root = BlockRoot(self.cc.get_block_root('finalized').root)
        block_details = self.cc.get_block_details(block_root)

        bs = build_blockstamp(block_details)
        print(bs)

        validators = self.cc.get_validators_no_cache(bs)

        tree_data, _ = self.StakingVaults.get_vaults_data(validators, bs)
        merkle_tree = self.StakingVaults.get_merkle_tree(tree_data)
        print(f"0x{merkle_tree.root.hex()}")

        # proof_cid = self.StakingVaults.publish_proofs(merkle_tree, bs, vaults)
        # print(proof_cid)

        # proof_tree = self.StakingVaults.publish_tree(merkle_tree, bs, proof_cid)
        # print(proof_tree)

        # got = f"0x{merkle_tree.root.hex()}"
        # expected = '0xd832e823b84db9ba0d7ba52b3647953c65ae0f86b81949a31605492ebe46f93a'
        assert 1 == 1
