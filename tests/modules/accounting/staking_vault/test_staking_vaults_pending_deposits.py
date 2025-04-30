# test_my_class.py

from unittest.mock import MagicMock

import pytest
from eth_typing import ChecksumAddress, BlockNumber, HexAddress, HexStr
from web3.types import Timestamp

from src.main import ipfs_providers
from src.modules.accounting.staking_vaults import StakingVaults
from src.modules.accounting.types import VaultInfo
from src.providers.consensus.types import Validator, ValidatorState, PendingDeposit
from src.providers.ipfs import MultiIPFSProvider
from src.types import BlockStamp, ValidatorIndex, Gwei, EpochNumber, SlotNumber, BlockHash, StateRoot


class TestStakingVaults:
    ipfs_client: MultiIPFSProvider
    staking_vaults: StakingVaults

    def setup_method(self):
        self.ipfs_client = MultiIPFSProvider(ipfs_providers(), retries=3)

        # Vault addresses
        vault_adr_0 = ChecksumAddress(HexAddress(HexStr('0x652b70E0Ae932896035d553fEaA02f37Ab34f7DC')))

        # --- VaultHub Mock ---
        vault_hub_mock = MagicMock()
        vault_hub_mock.get_all_vaults.return_value = [
            VaultInfo(
                vault=vault_adr_0,
                balance=0,
                in_out_delta=2000000000000000000,
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                liability_shares=0,
            ),
        ]

        # --- ConsensusClient Mock ---
        cc_mock = MagicMock()
        cc_mock.get_pending_deposits.return_value = []

        # --- Web3 Mock ---
        w3_mock = MagicMock()

        self.staking_vaults = StakingVaults(w3_mock, cc_mock, self.ipfs_client, vault_hub_mock)

    @pytest.mark.unit
    def test_get_vaults_data_multiple_pending_deposits(self):
        bs = BlockStamp(
            state_root=StateRoot(HexStr('0xcdbb26ef98f4f6c46262f34e980dcc92c28268ba6ca9b7d45668eb0c23cad3c3')),
            slot_number=SlotNumber(7314880),
            block_hash=BlockHash(HexStr('0xbb3ba9405346f2448e9fa02b110539dde714e6e3f06bd5207dc29e14db353a3a')),
            block_number=BlockNumber(8027890),
            block_timestamp=Timestamp(1743512160),
        )

        validators: list[Validator] = [
            Validator(
                index=ValidatorIndex(1986),
                balance=Gwei(0),
                validator=ValidatorState(
                    pubkey='0xa5d9411ef615c74c9240634905d5ddd46dc40a87a09e8cc0332afddb246d291303e452a850917eefe09b3b8c70a307ce',
                    withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                    effective_balance=Gwei(0),
                    slashed=False,
                    activation_eligibility_epoch=EpochNumber(226130),
                    activation_epoch=EpochNumber(226136),
                    exit_epoch=EpochNumber(227556),
                    withdrawable_epoch=EpochNumber(227812),
                ),
            ),
        ]

        pending_deposits: list[PendingDeposit] = [
            # Invalid (generated with fork_version 0x10000910, Hoodi)
            PendingDeposit(
                pubkey='0x8f6ef94afaab1b6a693a4e65bcec154a2a285eb8e0aa7f9f8a8c596d4cf98cac8b981d77d1af0427dbaa5a37fab77b80',
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                amount=Gwei(1000000000),
                signature='0xb859ffb4f3b6ead09dc2be1ac3902194d84a17efe4da195c07c57e8593f2bba4b58d74da113db0dddc96813808a106e215044670bd4230af50ed812a41d5cca0c4dfbffd0d9e0129cfbaf1dbcef9d7479bb27301aa74e1a69e3306b59eb051bb',
                slot=SlotNumber(259387),
            ),
            # Valid (generated with fork_version 0x00000000, Mainnet)
            PendingDeposit(
                pubkey='0x8f6ef94afaab1b6a693a4e65bcec154a2a285eb8e0aa7f9f8a8c596d4cf98cac8b981d77d1af0427dbaa5a37fab77b80',
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                amount=Gwei(1000000000),
                signature='0xa8e06b7ad322e27b4aab71c9901f2196c288b9dd616aefbef9eb58084094ddc2e220cbec0024b563918f8ad18ad680ab062b7a09ec5a2287da5f1ef3ab9073f3c6287faaba714bb347958a0563f2aeaa4f7eb56cabeb29a063e964e93c1020db',
                slot=SlotNumber(259388),
            ),
            # Again for hoodi, but should be counted as valid
            PendingDeposit(
                pubkey='0x8f6ef94afaab1b6a693a4e65bcec154a2a285eb8e0aa7f9f8a8c596d4cf98cac8b981d77d1af0427dbaa5a37fab77b80',
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                amount=Gwei(1000000000),
                signature='0xb859ffb4f3b6ead09dc2be1ac3902194d84a17efe4da195c07c57e8593f2bba4b58d74da113db0dddc96813808a106e215044670bd4230af50ed812a41d5cca0c4dfbffd0d9e0129cfbaf1dbcef9d7479bb27301aa74e1a69e3306b59eb051bb',
                slot=SlotNumber(259389),
            ),
        ]

        tree_data, vault_data = self.staking_vaults.get_vaults_data(validators, pending_deposits, bs)
        merkle_tree = self.staking_vaults.get_merkle_tree(tree_data)
        got = f"0x{merkle_tree.root.hex()}"
        expected = '0x1e258599def3fd5b123849e87603c4581fb6a6a607d1bb541e6460fe44915a11'
        assert got == expected
        assert len(merkle_tree.root) == 32

        # (address, total_value, in_out_delta, fees, liability_shares)
        expected_tree_data = [
            ('0x652b70E0Ae932896035d553fEaA02f37Ab34f7DC', 2000000000000000000, 2000000000000000000, 0, 0),
        ]

        assert expected_tree_data == tree_data

    @pytest.mark.unit
    def test_front_running_pending_deposits_protection(self):
        bs = BlockStamp(
            state_root=StateRoot(HexStr('0xcdbb26ef98f4f6c46262f34e980dcc92c28268ba6ca9b7d45668eb0c23cad3c3')),
            slot_number=SlotNumber(7314880),
            block_hash=BlockHash(HexStr('0xbb3ba9405346f2448e9fa02b110539dde714e6e3f06bd5207dc29e14db353a3a')),
            block_number=BlockNumber(8027890),
            block_timestamp=Timestamp(1743512160),
        )

        validators: list[Validator] = [
            Validator(
                index=ValidatorIndex(1986),
                balance=Gwei(0),
                validator=ValidatorState(
                    pubkey='0xa5d9411ef615c74c9240634905d5ddd46dc40a87a09e8cc0332afddb246d291303e452a850917eefe09b3b8c70a307ce',
                    withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                    effective_balance=Gwei(0),
                    slashed=False,
                    activation_eligibility_epoch=EpochNumber(226130),
                    activation_epoch=EpochNumber(226136),
                    exit_epoch=EpochNumber(227556),
                    withdrawable_epoch=EpochNumber(227812),
                ),
            ),
        ]

        pending_deposits: list[PendingDeposit] = [
            # Front running deposit with wrong withdrawal credentials
            PendingDeposit(
                pubkey='0x8f6ef94afaab1b6a693a4e65bcec154a2a285eb8e0aa7f9f8a8c596d4cf98cac8b981d77d1af0427dbaa5a37fab77b80',
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f000',
                amount=Gwei(1000000000),
                signature='0x8a608c679a35a21a5542af583b77fc303b6ad138b5d129b9df323aac2ced17cf36a399ee3d1d68203b495ac0dfdb46161291e8b4d6bf6b4d155bd0a9dd6c3fc158cd90e4e125c8eac8d7bc4ed99b6b8681f32a9481ad087e5229a569255bb8cc',
                slot=SlotNumber(259387),
            ),
            # Valid deposit with correct withdrawal credentials
            PendingDeposit(
                pubkey='0x8f6ef94afaab1b6a693a4e65bcec154a2a285eb8e0aa7f9f8a8c596d4cf98cac8b981d77d1af0427dbaa5a37fab77b80',
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                amount=Gwei(1000000000),
                signature='0xa8e06b7ad322e27b4aab71c9901f2196c288b9dd616aefbef9eb58084094ddc2e220cbec0024b563918f8ad18ad680ab062b7a09ec5a2287da5f1ef3ab9073f3c6287faaba714bb347958a0563f2aeaa4f7eb56cabeb29a063e964e93c1020db',
                slot=SlotNumber(259388),
            ),
        ]

        tree_data, vault_data = self.staking_vaults.get_vaults_data(validators, pending_deposits, bs)
        merkle_tree = self.staking_vaults.get_merkle_tree(tree_data)
        got = f"0x{merkle_tree.root.hex()}"
        expected = '0x1c0cda951522f541abff34a2e5bd412a02db171ce64358978204c274103298e2'
        assert got == expected
        assert len(merkle_tree.root) == 32

        # (address, total_value, in_out_delta, fees, liability_shares)
        expected_tree_data = [
            ('0x652b70E0Ae932896035d553fEaA02f37Ab34f7DC', 0, 2000000000000000000, 0, 0),
        ]

        assert expected_tree_data == tree_data
