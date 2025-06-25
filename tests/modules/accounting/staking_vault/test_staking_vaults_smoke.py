import os
from typing import cast

import pytest
from web3.types import Wei
from web3_multi_provider import init_metrics

from src import variables
from src.main import ipfs_providers
from src.modules.accounting.accounting import Accounting
from src.modules.accounting.staking_vaults import StakingVaults
from src.modules.submodules.types import ChainConfig
from src.providers.execution.contracts.accounting_oracle import AccountingOracleContract
from src.providers.execution.contracts.hash_consensus import HashConsensusContract
from src.providers.execution.contracts.lazy_oracle import LazyOracleContract
from src.providers.execution.contracts.lido import LidoContract
from src.providers.execution.contracts.lido_locator import LidoLocatorContract
from src.providers.execution.contracts.oracle_daemon_config import (
    OracleDaemonConfigContract,
)
from src.providers.execution.contracts.vault_hub import VaultHubContract
from src.providers.ipfs import MultiIPFSProvider
from src.types import BlockRoot, BlockStamp, ELVaultBalance
from src.utils.apr import calculate_steth_apr
from src.utils.blockstamp import build_blockstamp
from src.web3py.contract_tweak import tweak_w3_contracts
from src.web3py.extensions import (
    ConsensusClientModule,
    KeysAPIClientModule,
    LazyCSM,
    LidoContracts,
    LidoValidatorsProvider,
    TransactionUtils,
)
from src.web3py.types import Web3

EXECUTION_CLIENT_URI = os.getenv('EXECUTION_CLIENT_URI')
CONSENSUS_CLIENT_URI = os.getenv('CONSENSUS_CLIENT_URI')

@pytest.mark.skip(reason="Skipping all tests in this class on CI. Cause it's used for local testing")
# @pytest.mark.testnet
# @pytest.mark.integration
class TestStakingVaultsSmoke:
    cc: ConsensusClientModule
    ipfs_client: MultiIPFSProvider

    def setup_method(self):
        self.web3 = Web3(Web3.HTTPProvider(EXECUTION_CLIENT_URI))
        tweak_w3_contracts(self.web3)

        self.cc = ConsensusClientModule([CONSENSUS_CLIENT_URI], self.web3)
        self.kac = KeysAPIClientModule(variables.KEYS_API_URI, self.web3)
        self.ipfs_client = MultiIPFSProvider(ipfs_providers(), retries=3)

        self.web3.attach_modules(
            {
                'lido_contracts': LidoContracts,
                'lido_validators': LidoValidatorsProvider,
                'transaction': TransactionUtils,
                'csm': LazyCSM,
                'cc': lambda: self.cc,  # type: ignore[dict-item]
                'kac': lambda: self.kac,  # type: ignore[dict-item]
                'ipfs': lambda: self.ipfs_client,  # type: ignore[dict-item]
            }
        )

        self.web3.staking_vaults = StakingVaults(
            self.web3,
            self.cc,
            self.ipfs_client,
            self.web3.lido_contracts.lido,
            self.web3.lido_contracts.vault_hub,
            self.web3.lido_contracts.lazy_oracle,
            self.web3.lido_contracts.oracle_daemon_config,
        )
        init_metrics()
        self.accounting = Accounting(self.web3)

        self.lido_locator: LidoLocatorContract = cast(
            LidoLocatorContract,
            self.web3.eth.contract(
                address=variables.LIDO_LOCATOR_ADDRESS,
                ContractFactoryClass=LidoLocatorContract,
                decode_tuples=True,
            ),
        )

        self.lido: LidoContract = cast(
            LidoContract,
            self.web3.eth.contract(
                address=self.lido_locator.lido(),
                ContractFactoryClass=LidoContract,
                decode_tuples=True,
            ),
        )

        self.lazy_oracle: LazyOracleContract = cast(
            LazyOracleContract,
            self.web3.eth.contract(
                address=self.lido_locator.lazy_oracle(),
                ContractFactoryClass=LazyOracleContract,
                decode_tuples=True,
            ),
        )

        vault_hub: VaultHubContract = cast(
            VaultHubContract,
            self.web3.eth.contract(
                address=self.lido_locator.lazy_oracle(),
                ContractFactoryClass=VaultHubContract,
                decode_tuples=True,
            ),
        )

        daemon_config: OracleDaemonConfigContract = cast(
            OracleDaemonConfigContract,
            self.web3.eth.contract(
                address=self.lido_locator.oracle_daemon_config(),
                ContractFactoryClass=OracleDaemonConfigContract,
                decode_tuples=True,
            ),
        )

        self.accounting_oracle: AccountingOracleContract = cast(
            AccountingOracleContract,
            self.web3.eth.contract(
                address=self.lido_locator.accounting_oracle(),
                ContractFactoryClass=AccountingOracleContract,
                decode_tuples=True,
            ),
        )

        self.hash_consensus_contract: HashConsensusContract = cast(
            HashConsensusContract,
            self.web3.eth.contract(
                address=self.accounting_oracle.get_consensus_contract(),
                ContractFactoryClass=HashConsensusContract,
                decode_tuples=True,
            ),
        )

        # self.accounting_oracle.get_consensus_contract

        # self.StakingVaults = StakingVaults(self.web3, self.cc, self.ipfs_client, lido, vault_hub, lazy_oracle, daemon_config)

    def get_el_vault_balance(self, blockstamp: BlockStamp) -> ELVaultBalance:
        return ELVaultBalance(
            Wei(
                self.web3.eth.get_balance(
                    self.lido_locator.el_rewards_vault(blockstamp.block_hash),
                    block_identifier=blockstamp.block_hash,
                )
            )
        )

    def test_manual_vault_report(self):
        block_root = BlockRoot(self.cc.get_block_root('finalized').root)
        block_details = self.cc.get_block_details(block_root)

        bs = build_blockstamp(block_details)
        # el_balance = self.get_el_vault_balance(bs)

        modules_fee, treasury_fee, base_precision = (
            self.web3.lido_contracts.staking_router.get_staking_fee_aggregate_distribution('latest')
        )
        lido_fee_bp = ((modules_fee + treasury_fee) / base_precision) / 0.0001  # 1_000

        rebased_event = self.web3.lido_contracts.lido.get_last_token_rebased_event(
            bs.block_number - 7200, bs.block_number
        )

        time_elapsed = 2316

        predicted_apr = calculate_steth_apr(
            rebased_event.pre_total_shares,
            rebased_event.pre_total_ether,
            rebased_event.post_total_shares,
            rebased_event.post_total_ether,
            time_elapsed,
        )

        predicted_apr_bp = predicted_apr * 100
        # core_apr_1 = int(predicted_apr_bp // (lido_fee_bp // 10_000))
        core_apr_2 = int(predicted_apr_bp / lido_fee_bp)
        core_apr_3 = int(predicted_apr_bp // lido_fee_bp)
        core_apr_4 = int(2.126029181960391e-12 / 0.1)

        print(predicted_apr, predicted_apr_bp, lido_fee_bp)
        print(core_apr_2)
        print(core_apr_3)
        print(core_apr_4)

        # core_apr = int(predicted_apr // (lido_fee_bp // 10_000))

        # chain_config = self.hash_consensus_contract.get_chain_config()
        # print(chain_config)

        # validators = self.cc.get_validators_no_cache(bs)
        # pending_deposites = self.cc.get_pending_deposits(bs)

        # tree_data, _, _ = self.StakingVaults.get_vaults_data(bs, validators, pending_deposites)
        # merkle_tree = self.StakingVaults.get_merkle_tree(tree_data)
        # print(f"0x{merkle_tree.root.hex()}")

        # proof_cid = self.StakingVaults.publish_proofs(merkle_tree, bs, vaults)
        # print(proof_cid)

        # proof_tree = self.StakingVaults.publish_tree(merkle_tree, bs, proof_cid)
        # print(proof_tree)

        # got = f"0x{merkle_tree.root.hex()}"
        # expected = '0xd832e823b84db9ba0d7ba52b3647953c65ae0f86b81949a31605492ebe46f93a'
        assert 1 == 1
