from unittest.mock import MagicMock

import pytest
from eth_typing import BlockNumber, ChecksumAddress, HexAddress, HexStr
from web3.types import Timestamp, Wei

from src.main import ipfs_providers
from src.modules.accounting.staking_vaults import StakingVaults
from src.modules.accounting.types import VaultInfo, VaultsMap
from src.providers.consensus.types import PendingDeposit, Validator, ValidatorState
from src.providers.ipfs import MultiIPFSProvider
from src.types import (
    BlockHash,
    BlockStamp,
    EpochNumber,
    Gwei,
    SlotNumber,
    StateRoot,
    ValidatorIndex,
)


class TestStakingVaults:
    ipfs_client: MultiIPFSProvider
    staking_vaults: StakingVaults

    def setup_method(self):
        self.ipfs_client = MultiIPFSProvider(ipfs_providers(), retries=3)

        # Vault addresses
        vault_adr_0 = ChecksumAddress(HexAddress(HexStr('0xE312f1ed35c4dBd010A332118baAD69d45A0E302')))
        vault_adr_1 = ChecksumAddress(HexAddress(HexStr('0x652b70E0Ae932896035d553fEaA02f37Ab34f7DC')))
        vault_adr_2 = ChecksumAddress(HexAddress(HexStr('0x20d34FD0482E3BdC944952D0277A306860be0014')))
        vault_adr_3 = ChecksumAddress(HexAddress(HexStr('0x60B614c42d92d6c2E68AF7f4b741867648aBf9A4')))

        # --- VaultHub Mock ---
        self.vaults: VaultsMap = {
            vault_adr_0: VaultInfo(
                vault_ind=1,
                vault=vault_adr_0,
                balance=Wei(1000000000000000000),
                in_out_delta=Wei(1000000000000000000),
                withdrawal_credentials='0x020000000000000000000000e312f1ed35c4dbd010a332118baad69d45a0e302',
                liability_shares=0,
                share_limit=0,
                reserve_ratioBP=0,
                forced_rebalance_thresholdBP=0,
                infra_feeBP=0,
                liquidity_feeBP=0,
                reservation_feeBP=0,
                pending_disconnect=False,
                mintable_capacity_StETH=0,
            ),
            vault_adr_1: VaultInfo(
                vault_ind=2,
                vault=vault_adr_1,
                balance=Wei(0),
                in_out_delta=Wei(2000000000000000000),
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                liability_shares=490000000000000000,
                share_limit=0,
                reserve_ratioBP=0,
                forced_rebalance_thresholdBP=0,
                infra_feeBP=0,
                liquidity_feeBP=0,
                reservation_feeBP=0,
                pending_disconnect=False,
                mintable_capacity_StETH=0,
            ),
            vault_adr_2: VaultInfo(
                vault_ind=3,
                vault=vault_adr_2,
                balance=Wei(2000900000000000000),
                in_out_delta=Wei(2000900000000000000),
                withdrawal_credentials='0x02000000000000000000000020d34fd0482e3bdc944952d0277a306860be0014',
                liability_shares=1200000000000010001,
                share_limit=0,
                reserve_ratioBP=0,
                forced_rebalance_thresholdBP=0,
                infra_feeBP=0,
                liquidity_feeBP=0,
                reservation_feeBP=0,
                pending_disconnect=False,
                mintable_capacity_StETH=0,
            ),
            vault_adr_3: VaultInfo(
                vault_ind=4,
                vault=vault_adr_3,
                balance=Wei(1000000000000000000),
                in_out_delta=Wei(1000000000000000000),
                withdrawal_credentials='0x02000000000000000000000060b614c42d92d6c2e68af7f4b741867648abf9a4',
                liability_shares=0,
                share_limit=0,
                reserve_ratioBP=0,
                forced_rebalance_thresholdBP=0,
                infra_feeBP=0,
                liquidity_feeBP=0,
                reservation_feeBP=0,
                pending_disconnect=False,
                mintable_capacity_StETH=0,
            ),
        }

        # --- Web3 Mock ---
        w3_mock = MagicMock()
        cc_mock = MagicMock()
        lido_mock = MagicMock()
        lazy_oracle_mock = MagicMock()
        daemon_config_mock = MagicMock()
        vault_hub_mock = MagicMock()

        self.staking_vaults = StakingVaults(
            w3_mock, cc_mock, self.ipfs_client, lido_mock, vault_hub_mock, lazy_oracle_mock, daemon_config_mock
        )

    @pytest.mark.unit
    def test_get_vaults_total_values(self):
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
                    withdrawal_credentials='0x020000000000000000000000e312f1ed35c4dbd010a332118baad69d45a0e302',
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
                balance=Gwei(40000000000),
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
            Validator(
                index=ValidatorIndex(1987),
                balance=Gwei(50000000000),
                validator=ValidatorState(
                    pubkey='0xa5d9411ef615c74c9240634905d5ddd46dc40a87a09e8cc0332afddb246d291303e452a850917eefe09b3b8c70a307ce',
                    withdrawal_credentials='0x02000000000000000000000020d34fd0482e3bdc944952d0277a306860be0014',
                    effective_balance=Gwei(0),
                    slashed=False,
                    activation_eligibility_epoch=EpochNumber(226130),
                    activation_epoch=EpochNumber(226136),
                    exit_epoch=EpochNumber(227556),
                    withdrawable_epoch=EpochNumber(227812),
                ),
            ),
            Validator(
                index=ValidatorIndex(1987),
                balance=Gwei(60000000000),
                validator=ValidatorState(
                    pubkey='0xa5d9411ef615c74c9240634905d5ddd46dc40a87a09e8cc0332afddb246d291303e452a850917eefe09b3b8c70a307ce',
                    withdrawal_credentials='0x02000000000000000000000060b614c42d92d6c2e68af7f4b741867648abf9a4',
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
            # Valid
            PendingDeposit(
                pubkey='0xa50a7821c793e80710f51c681b28f996e5c2f1fa00318dbf91b5844822d58ac2fef892b79aea386a3b97829e090a393e',
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                amount=Gwei(1000000000),
                signature='0xb5b222b452892bd62a7d2b4925e15bf9823c4443313d86d3e1fe549c86aa8919d0cdd1d5b60d9d3184f3966ced21699f124a14a0d8c1f1ae3e9f25715f40c3e7b81a909424c60ca7a8cbd79f101d6bd86ce1bdd39701cf93b2eecce10699f40b',
                slot=SlotNumber(259388),
            ),
            # Invalid
            PendingDeposit(
                pubkey='0x8c96ad1b9a1acf4a898009d96293d191ab911b535cd1e6618e76897b5fa239a7078f1fbf9de8dd07a61a51b137c74a87',
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                amount=Gwei(1000000000),
                signature='0x978f286178050a3dbf6f8551b8020f72dd1de8223fc9cb8553d5ebb22f71164f4278d9b970467084a9dcd54ad07ec8d60792104ff82887b499346f3e8adc55a86f26bfbb032ac2524da42d5186c5a8ed0ccf9d98e9f6ff012cfafbd712335aa5',
                slot=SlotNumber(259654),
            ),
            # Invalid
            PendingDeposit(
                pubkey='0x99eeb66e77fef5c71d3b303774ecded0d52d521e8d665c2d0f350c33f5f82e7ddd88dd9bc4f8014fb22820beda3a8a85',
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                amount=Gwei(1000000000),
                signature='0xb4ea337eb8d0fc47361672d4a153dbe3cd943a0418c9f1bc586bca95cdcf8615d60a2394b7680276c4597a2524f9bcf1088c40a08902841ff68d508a9f825803b9fac3bc6333cf3afa7503f560ccf6f689be5b0f5d08fa9e21cb203aa1f53259',
                slot=SlotNumber(260393),
            ),
        ]

        vaults_total_values = self.staking_vaults.get_vaults_total_values(self.vaults, validators, pending_deposits)
        expected = [33834904184000000000, 41000000000000000000, 52000900000000000000, 61000000000000000000]
        assert vaults_total_values == expected

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

        vaults_total_values = self.staking_vaults.get_vaults_total_values(self.vaults, validators, pending_deposits)
        expected = [1000000000000000000, 2000000000000000000, 2000900000000000000, 1000000000000000000]
        assert vaults_total_values == expected

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

        vaults_total_values = self.staking_vaults.get_vaults_total_values(self.vaults, validators, pending_deposits)
        expected = [1000000000000000000, 0, 2000900000000000000, 1000000000000000000]

        assert vaults_total_values == expected

    @pytest.mark.unit
    def test_existing_validator_with_wrong_withdrawal_credentials(self):
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
            Validator(
                index=ValidatorIndex(1986),
                balance=Gwei(0),
                validator=ValidatorState(
                    pubkey='0x8f6ef94afaab1b6a693a4e65bcec154a2a285eb8e0aa7f9f8a8c596d4cf98cac8b981d77d1af0427dbaa5a37fab77b80',
                    withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f000',
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
            # Valid deposit with correct withdrawal credentials
            PendingDeposit(
                pubkey='0x8f6ef94afaab1b6a693a4e65bcec154a2a285eb8e0aa7f9f8a8c596d4cf98cac8b981d77d1af0427dbaa5a37fab77b80',
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                amount=Gwei(1000000000),
                signature='0xa8e06b7ad322e27b4aab71c9901f2196c288b9dd616aefbef9eb58084094ddc2e220cbec0024b563918f8ad18ad680ab062b7a09ec5a2287da5f1ef3ab9073f3c6287faaba714bb347958a0563f2aeaa4f7eb56cabeb29a063e964e93c1020db',
                slot=SlotNumber(259388),
            ),
        ]

        vaults_total_values = self.staking_vaults.get_vaults_total_values(self.vaults, validators, pending_deposits)

        expected = [1000000000000000000, 0, 2000900000000000000, 1000000000000000000]

        assert vaults_total_values == expected
