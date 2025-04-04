# test_my_class.py

from unittest.mock import MagicMock

import pytest
from eth_typing import ChecksumAddress, BlockNumber, HexAddress, HexStr
from web3.types import Timestamp

from src.main import ipfs_providers
from src.modules.accounting.staking_vaults import StakingVaults
from src.modules.accounting.types import VaultSocket
from src.providers.consensus.types import Validator, ValidatorState
from src.providers.ipfs import MultiIPFSProvider
from src.types import BlockStamp, ValidatorIndex, Gwei, EpochNumber, SlotNumber, BlockHash, StateRoot


class TestStakingVaults:
    ipfs_client: MultiIPFSProvider
    staking_vaults: StakingVaults

    def setup_method(self):
        self.ipfs_client = MultiIPFSProvider(ipfs_providers(), retries=3)

        # Vault addresses
        vault_adr_0 = ChecksumAddress(HexAddress(HexStr('0xEcB7C8D2BaF7270F90066B4cd8286e2CA1154F60')))
        vault_adr_1 = ChecksumAddress(HexAddress(HexStr('0xc1F9c4a809cbc6Cb2cA60bCa09cE9A55bD5337Db')))
        vault_addresses = [vault_adr_0, vault_adr_1]

        # --- VaultHub Mock ---
        vault_hub_mock = MagicMock()
        vault_hub_mock.get_vaults_count.return_value = len(vault_addresses)

        vault_sockets = [
            VaultSocket(
                vault=vault_adr_0,
                share_limit=10000,
                shares_minted=0,
                reserve_ratio_bp=1000,
                rebalance_threshold_bp=800,
                treasury_fee_bp=500,
                pending_disconnect=False,
            ),
            VaultSocket(
                vault=vault_adr_1,
                share_limit=10000,
                shares_minted=1,
                reserve_ratio_bp=1000,
                rebalance_threshold_bp=800,
                treasury_fee_bp=500,
                pending_disconnect=False,
            ),
        ]

        vault_hub_mock.vault_socket.side_effect = lambda idx, _: vault_sockets[idx]

        # --- ConsensusClient Mock ---
        cc_mock = MagicMock()
        cc_mock.get_pending_deposits.return_value = []

        # --- Web3 Mock ---
        w3_mock = MagicMock()

        # Balances
        balances = {
            vault_adr_0: 66_951_606_691_371_698_360,
            vault_adr_1: 2_500_000_000_000_000_000,
        }
        w3_mock.eth.get_balance.side_effect = lambda address, block_identifier=None: balances.get(address, 0)
        w3_mock.to_checksum_address.side_effect = lambda x: x

        # Vault Contracts (StakingVaultContract)
        vault_contracts = {
            vault_adr_0: MagicMock(
                in_out_delta=MagicMock(return_value=33_000_000_000_000_000_000),
                withdrawal_credentials=MagicMock(
                    return_value="0x020000000000000000000000ecb7c8d2baf7270f90066b4cd8286e2ca1154f60"
                ),
            ),
            vault_adr_1: MagicMock(
                in_out_delta=MagicMock(return_value=2_500_000_000_000_000_000),
                withdrawal_credentials=MagicMock(
                    return_value="0x020000000000000000000000c1f9c4a809cbc6cb2ca60bca09ce9a55bd5337db"
                ),
            ),
        }
        w3_mock.eth.contract.side_effect = lambda address, **kwargs: vault_contracts.get(address)

        self.staking_vaults = StakingVaults(w3_mock, cc_mock, self.ipfs_client, vault_hub_mock)

    @pytest.mark.unit
    def test_manual_vault_report(self):
        bs = BlockStamp(
            state_root=StateRoot(HexStr('0xcdbb26ef98f4f6c46262f34e980dcc92c28268ba6ca9b7d45668eb0c23cad3c3')),
            slot_number=SlotNumber(7314880),
            block_hash=BlockHash(HexStr('0xbb3ba9405346f2448e9fa02b110539dde714e6e3f06bd5207dc29e14db353a3a')),
            block_number=BlockNumber(8027890),
            block_timestamp=Timestamp(1743512160),
        )

        validators: list[Validator] = [
            Validator(
                index=ValidatorIndex(1985),
                balance=Gwei(32834904184),
                validator=ValidatorState(
                    pubkey='0x862d53d9e4313374d202f2b28e6ffe64efb0312f9c2663f2eef67b72345faa8932b27f9b9bb7b476d9b5e418fea99124',
                    withdrawal_credentials='0x020000000000000000000000ecb7c8d2baf7270f90066b4cd8286e2ca1154f60',
                    effective_balance=Gwei(32000000000),
                    slashed=False,
                    activation_eligibility_epoch=EpochNumber(225469),
                    activation_epoch=EpochNumber(225475),
                    exit_epoch=EpochNumber(18446744073709551615),
                    withdrawable_epoch=EpochNumber(18446744073709551615),
                ),
            ),
            Validator(
                index=ValidatorIndex(1986),
                balance=Gwei(0),
                validator=ValidatorState(
                    pubkey='0xa5d9411ef615c74c9240634905d5ddd46dc40a87a09e8cc0332afddb246d291303e452a850917eefe09b3b8c70a307ce',
                    withdrawal_credentials='0x020000000000000000000000ecb7c8d2baf7270f90066b4cd8286e2ca1154f60',
                    effective_balance=Gwei(0),
                    slashed=False,
                    activation_eligibility_epoch=EpochNumber(226130),
                    activation_epoch=EpochNumber(226136),
                    exit_epoch=EpochNumber(227556),
                    withdrawable_epoch=EpochNumber(227812),
                ),
            ),
        ]

        _, _, tree_data, _ = self.staking_vaults.get_vaults_data(validators, bs)
        merkle_tree = self.staking_vaults.get_merkle_tree(tree_data)
        got = f"0x{merkle_tree.root.hex()}"
        expected = '0x8947e4ef0354707240394a85ca9c2dcad15f52c773a955a0b827f50f5afbb93b'
        assert got == expected

        # proof_cid = self.StakingVaults.publish_proofs(merkle_tree, bs, vaults)
        # print(proof_cid)

        # proof_tree = self.StakingVaults.publish_tree(merkle_tree, bs, "2312")
        # print(proof_tree)

        # got = f"0x{merkle_tree.root.hex()}"
        # expected = '0xd832e823b84db9ba0d7ba52b3647953c65ae0f86b81949a31605492ebe46f93a'
        # assert got == expected
