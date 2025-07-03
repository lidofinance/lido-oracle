import copy
from decimal import Decimal, ROUND_UP
from unittest.mock import MagicMock

import pytest
from eth_typing import BlockNumber, ChecksumAddress, HexAddress, HexStr
from web3.types import Wei

from src.modules.accounting.accounting import Accounting
from src.modules.accounting.events import (
    BurnedSharesOnVaultEvent,
    MintedSharesOnVaultEvent,
    VaultFeesUpdatedEvent,
)
from src.modules.accounting.staking_vaults import StakingVaults
from src.modules.accounting.types import (
    ExtraValue,
    MerkleTreeData,
    MerkleValue,
    VaultInfo,
    VaultsMap,
    VaultTotalValueMap,
    VaultFee,
)
from src.providers.consensus.types import PendingDeposit, Validator, ValidatorState
from src.types import EpochNumber, Gwei, SlotNumber, ValidatorIndex


class TestStakingVaults:
    staking_vaults: StakingVaults

    vault_adr_0 = ChecksumAddress(HexAddress(HexStr('0xE312f1ed35c4dBd010A332118baAD69d45A0E302')))
    vault_adr_1 = ChecksumAddress(HexAddress(HexStr('0x652b70E0Ae932896035d553fEaA02f37Ab34f7DC')))
    vault_adr_2 = ChecksumAddress(HexAddress(HexStr('0x20d34FD0482E3BdC944952D0277A306860be0014')))
    vault_adr_3 = ChecksumAddress(HexAddress(HexStr('0x60B614c42d92d6c2E68AF7f4b741867648aBf9A4')))

    def setup_method(self):
        # Vault addresses

        # --- VaultHub Mock ---
        self.vaults: VaultsMap = {
            self.vault_adr_0: VaultInfo(
                vault=self.vault_adr_0,
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
            self.vault_adr_1: VaultInfo(
                vault=self.vault_adr_1,
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
            self.vault_adr_2: VaultInfo(
                vault=self.vault_adr_2,
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
            self.vault_adr_3: VaultInfo(
                vault=self.vault_adr_3,
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
        vault_hub_mock = MagicMock()
        ipfs_client = MagicMock()
        account_oracle_mock = MagicMock()

        self.staking_vaults = StakingVaults(
            w3_mock, cc_mock, ipfs_client, lido_mock, vault_hub_mock, lazy_oracle_mock, account_oracle_mock
        )

        self.accounting = Accounting(w3_mock)

    @pytest.mark.unit
    def test_get_vaults_total_values(self):
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
        expected = {
            self.vault_adr_0: 33834904184000000000,
            self.vault_adr_1: 41000000000000000000,
            self.vault_adr_2: 52000900000000000000,
            self.vault_adr_3: 61000000000000000000,
        }

        assert vaults_total_values == expected

    @pytest.mark.unit
    def test_get_vaults_data_multiple_pending_deposits(self):
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
        expected = {
            self.vault_adr_0: 1000000000000000000,
            self.vault_adr_1: 2000000000000000000,
            self.vault_adr_2: 2000900000000000000,
            self.vault_adr_3: 1000000000000000000,
        }

        assert vaults_total_values == expected

    @pytest.mark.unit
    def test_front_running_pending_deposits_protection(self):
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
        expected = {
            self.vault_adr_0: 1000000000000000000,
            self.vault_adr_1: 0,
            self.vault_adr_2: 2000900000000000000,
            self.vault_adr_3: 1000000000000000000,
        }

        assert vaults_total_values == expected

    @pytest.mark.unit
    def test_existing_validator_with_wrong_withdrawal_credentials(self):
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
        expected = {
            self.vault_adr_0: 1000000000000000000,
            self.vault_adr_1: 1000000000000000000,
            self.vault_adr_2: 2000900000000000000,
            self.vault_adr_3: 1000000000000000000,
        }
        assert vaults_total_values == expected

    pre_total_shares = 7598409496266444487755575
    pre_total_pooled_ether = Wei(9165134090291140983725643)
    post_total_shares = 7589357999778578274703354
    post_total_pooled_ether = Wei(9154964744971805725084856)
    modules_fee, treasury_fee, base_precision = (
        5121913857400931783,
        4878086142599068213,
        100000000000000000000,
    )  # APR ~ 0.03316002451606887481973829228
    core_ratio_apr = Decimal('0.03316002451606887481973829228')
    liability_shares = 2880 * 10**18
    reserve_ratioBP = 2000
    infra_feeBP = 100
    liquidity_feeBP = 650
    reservation_feeBP = 250
    mintable_capacity_StETH = 3200 * 10**18
    vault_total_value = 3200 * 10**18
    expected_infra_fee = Decimal('2907180231545764.36775787768')
    expected_reservation_liquidity_fee = Decimal('7267950578864410.91939469422')
    expected_liquidity_fee = Decimal('17007082495056342.00729679122')
    prev_fee = 22169367899378
    expected_total_fee = 27204382673365897  # 0.02720438267 ETH

    @pytest.mark.unit
    def test_fees(self):
        """
        Main purpose is check code behavior, not digits
        """
        vault1_adr = "0xVault1"
        prev_block_number = 0
        block_elapsed = 7_200

        mock_merkle_tree_data = MerkleTreeData(
            format="v1",
            leaf_encoding=["encoding1"],
            tree=["node1"],
            values=[
                MerkleValue(
                    vault1_adr,  # address
                    MagicMock(),  # total_value_wei
                    self.prev_fee,  # fee
                    MagicMock(),  # liability_shares
                    MagicMock(),  # slashing_reserve
                ),
            ],
            tree_indices=[0],
            block_number=BlockNumber(prev_block_number),
            block_hash=MagicMock(),
            ref_slot=MagicMock(),
            timestamp=MagicMock(),
            prev_tree_cid=MagicMock(),
            extra_values={
                vault1_adr: ExtraValue(0),
            },
        )

        vault1 = VaultInfo(
            vault=vault1_adr,
            liability_shares=self.liability_shares,
            reserve_ratioBP=self.reserve_ratioBP,
            infra_feeBP=self.infra_feeBP,
            liquidity_feeBP=self.liquidity_feeBP,
            reservation_feeBP=self.reservation_feeBP,
            mintable_capacity_StETH=self.mintable_capacity_StETH,
            balance=MagicMock(),
            withdrawal_credentials=MagicMock(),
            share_limit=MagicMock(),
            forced_rebalance_thresholdBP=MagicMock(),
            pending_disconnect=MagicMock(),
            in_out_delta=MagicMock(),
        )

        mock_prev_vault1 = copy.copy(vault1)
        mock_prev_vault1.liability_shares = 2879999910015672558976
        mock_prev_vault1.liquidity_feeBP = 300

        mock_prev_vaults = [mock_prev_vault1]

        vaults = {}
        vaults_total_values: VaultTotalValueMap = {
            ChecksumAddress(HexAddress(HexStr(vault1_adr))): self.vault_total_value
        }

        # 65020000000000000000,0x0200000000000000000000007228fc874c1d08cae68a558d7b650fc4862b1db7
        vaults[vault1.vault] = vault1

        vaults_fee_updated_events = [
            VaultFeesUpdatedEvent(
                block_number=3200,
                pre_infra_fee_bp=MagicMock(),
                pre_liquidity_fee_bp=400,
                infra_fee_bp=MagicMock(),
                pre_reservation_fee_bp=MagicMock(),
                reservation_fee_bp=MagicMock(),
                liquidity_fee_bp=650,
                vault=vault1_adr,
                event=MagicMock(),
                log_index=MagicMock(),
                transaction_index=MagicMock(),
                address=MagicMock(),
                transaction_hash=MagicMock(),
                block_hash=MagicMock(),
            )
        ]
        burned_shares_events = [
            BurnedSharesOnVaultEvent(
                block_number=3700,
                amount_of_shares=50_000_000,
                vault=vault1_adr,
                event=MagicMock(),
                log_index=MagicMock(),
                transaction_index=MagicMock(),
                address=MagicMock(),
                transaction_hash=MagicMock(),
                block_hash=MagicMock(),
            ),
        ]

        minted_shares_events = [
            MintedSharesOnVaultEvent(
                block_number=3600,
                amount_of_shares=8_998_437_744_1024,
                vault=vault1_adr,
                locked_amount=MagicMock(),
                event=MagicMock(),
                log_index=MagicMock(),
                transaction_index=MagicMock(),
                address=MagicMock(),
                transaction_hash=MagicMock(),
                block_hash=MagicMock(),
            )
        ]

        mock_prev_ipfs_report_cid = MagicMock()

        # --- Web3 Mock ---
        w3_mock = MagicMock()
        cc_mock = MagicMock()
        lido_mock = MagicMock()
        lazy_oracle_mock = MagicMock()
        vault_hub_mock = MagicMock()
        ipfs_client = MagicMock()
        account_oracle_mock = MagicMock()
        chain_config_mock = MagicMock()
        frame_mock = MagicMock()

        lazy_oracle_mock.get_all_vaults = MagicMock(return_value=mock_prev_vaults)
        vault_hub_mock.get_vaults_fee_updated_events = MagicMock(return_value=vaults_fee_updated_events)
        vault_hub_mock.get_minted_events = MagicMock(return_value=minted_shares_events)
        vault_hub_mock.get_burned_events = MagicMock(return_value=burned_shares_events)

        vault_hub_mock.get_vaults_rebalanced_events = MagicMock(return_value=[])
        vault_hub_mock.get_vaults_bad_debt_socialized_events = MagicMock(return_value=[])
        vault_hub_mock.get_written_off_to_be_internalized_events = MagicMock(return_value=[])

        self.staking_vaults = StakingVaults(
            w3_mock, cc_mock, ipfs_client, lido_mock, vault_hub_mock, lazy_oracle_mock, account_oracle_mock
        )
        self.staking_vaults._get_start_point_for_fee_calculations = MagicMock(
            return_value=[mock_merkle_tree_data, prev_block_number, MagicMock()]
        )

        mock_ref_block = MagicMock()
        mock_ref_block.block_number = prev_block_number + block_elapsed

        actual_fees = self.staking_vaults.get_vaults_fees(
            mock_ref_block,
            vaults,
            vaults_total_values,
            mock_prev_ipfs_report_cid,
            self.core_ratio_apr,
            self.pre_total_pooled_ether,
            self.pre_total_shares,
            chain_config_mock,
            frame_mock,
        )

        expected_fees = {
            vault1_adr: VaultFee(
                infra_fee=int(self.expected_infra_fee.to_integral_value(ROUND_UP)),
                liquidity_fee=int(self.expected_liquidity_fee.to_integral_value(ROUND_UP)),
                reservation_fee=int(self.expected_reservation_liquidity_fee.to_integral_value(ROUND_UP)),
                prev_fee=int(self.prev_fee),
            )
        }

        assert self.expected_total_fee == expected_fees[vault1_adr].total()
        assert actual_fees[ChecksumAddress(HexAddress(HexStr(vault1_adr)))].total() == expected_fees[vault1_adr].total()
        assert actual_fees == expected_fees

    @pytest.mark.parametrize(
        "vault_total_value, block_elapsed, core_apr_ratio, infra_fee_bp, expected_wei",
        [
            (vault_total_value, 7_200, core_ratio_apr, infra_feeBP, expected_infra_fee),
            (vault_total_value, 7_200 * 364, core_ratio_apr, infra_feeBP, Decimal('1058213604282658229.86386748')),
        ],
    )
    def test_infra_fee(self, vault_total_value, block_elapsed, core_apr_ratio, infra_fee_bp, expected_wei):
        result = StakingVaults.calc_fee_value(
            Decimal(vault_total_value), block_elapsed, Decimal(str(core_apr_ratio)), infra_fee_bp
        )

        assert result == expected_wei

    @pytest.mark.parametrize(
        "mintable_capacity_steth, block_elapsed, core_apr_ratio, reservation_fee_bp, expected_wei",
        [
            (
                mintable_capacity_StETH,
                7_200,
                core_ratio_apr,
                reservation_feeBP,
                expected_reservation_liquidity_fee,
            ),
            (
                mintable_capacity_StETH,
                7_200 * 364,
                core_ratio_apr,
                reservation_feeBP,
                Decimal('2645534010706645574.65966869'),
            ),
        ],
    )
    # TODO reservation_feeBP does not have references values from excel table
    def test_reservation_liquidity_fee(
        self, mintable_capacity_steth, block_elapsed, core_apr_ratio, reservation_fee_bp, expected_wei
    ):
        result = StakingVaults.calc_fee_value(
            mintable_capacity_steth, block_elapsed, Decimal(str(core_apr_ratio)), reservation_fee_bp
        )

        assert result == expected_wei

    vault1_adr = "0xVault1"
    test_data = [
        (
            vault1_adr,  # vault_address
            liability_shares,  # liability_shares
            liquidity_feeBP,  # 6.5% liquidity_fee_bp (6.5% * 10_000 = 650)
            {},  # No events
            0,  # prev_block_number
            7_200,  # current_block
            # assuming share rate is 1:1 for simplicity
            pre_total_pooled_ether,  # pre_total_pooled_ether (Wei)
            pre_total_shares,  # pre_total_shares (Shares)
            core_ratio_apr,  # core_apr_ratio (3%)
            (Decimal('20513697696884908.4459967120'), 2880000000000000000000),
        ),
        (
            vault1_adr,  # vault_address
            liability_shares,  # liability_shares
            liquidity_feeBP,  # 6.5% liquidity_fee_bp (6.5% * 10_000 = 650)
            {
                vault1_adr: [
                    MintedSharesOnVaultEvent(
                        block_number=3600,
                        amount_of_shares=8_998_437_744_1024,
                        vault=vault1_adr,
                        locked_amount=MagicMock(),
                        event=MagicMock(),
                        log_index=MagicMock(),
                        transaction_index=MagicMock(),
                        address=MagicMock(),
                        transaction_hash=MagicMock(),
                        block_hash=MagicMock(),
                    ),
                    BurnedSharesOnVaultEvent(
                        block_number=3700,
                        amount_of_shares=50_000_000,
                        vault=vault1_adr,
                        event=MagicMock(),
                        log_index=MagicMock(),
                        transaction_index=MagicMock(),
                        address=MagicMock(),
                        transaction_hash=MagicMock(),
                        block_hash=MagicMock(),
                    ),
                    VaultFeesUpdatedEvent(
                        block_number=3200,
                        pre_infra_fee_bp=MagicMock(),
                        pre_liquidity_fee_bp=400,
                        infra_fee_bp=MagicMock(),
                        pre_reservation_fee_bp=MagicMock(),
                        reservation_fee_bp=MagicMock(),
                        liquidity_fee_bp=650,
                        vault=vault1_adr,
                        event=MagicMock(),
                        log_index=MagicMock(),
                        transaction_index=MagicMock(),
                        address=MagicMock(),
                        transaction_hash=MagicMock(),
                        block_hash=MagicMock(),
                    ),
                ]
            },
            0,  # prev_block_number
            7_200,  # current_block
            pre_total_pooled_ether,  # pre_total_pooled_ether (Wei)
            pre_total_shares,  # pre_total_shares (Shares)
            core_ratio_apr,  # core_apr_ratio (3%)
            (expected_liquidity_fee, 2879999910015672558976),  # expected result: (fee, shares)
        ),
    ]

    @pytest.mark.parametrize(
        "vault_address, liability_shares, liquidity_fee_bp, events, prev_block_number, current_block, pre_total_pooled_ether, pre_total_shares, core_apr_ratio, expected",
        test_data,
    )
    def test_calc_liquidity_fee(
        self,
        vault_address,
        liability_shares,
        liquidity_fee_bp,
        events,
        prev_block_number,
        current_block,
        pre_total_pooled_ether,
        pre_total_shares,
        core_apr_ratio,
        expected,
    ):
        result = StakingVaults.calc_liquidity_fee(
            vault_address,
            liability_shares,
            liquidity_fee_bp,
            events,
            prev_block_number,
            current_block,
            pre_total_pooled_ether,
            pre_total_shares,
            core_apr_ratio,
        )

        assert result == expected
