import copy
import json
from collections import defaultdict
from decimal import Decimal, ROUND_UP
from unittest.mock import MagicMock

import pytest
from eth_typing import BlockNumber, ChecksumAddress, HexAddress, HexStr
from web3.types import Wei, Timestamp

from src.constants import TOTAL_BASIS_POINTS
from src.modules.accounting.events import (
    BurnedSharesOnVaultEvent,
    MintedSharesOnVaultEvent,
    VaultFeesUpdatedEvent,
    VaultRebalancedEvent,
    BadDebtWrittenOffToBeInternalizedEvent,
    BadDebtSocializedEvent,
    VaultConnectedEvent, VaultEventType,
)
from src.modules.submodules.types import ChainConfig, FrameConfig
from src.providers.ipfs import CID
from src.services.staking_vaults import StakingVaultsService
from src.modules.accounting.types import (
    ExtraValue,
    StakingVaultIpfsReport,
    MerkleValue,
    VaultInfo,
    VaultsMap,
    VaultTotalValueMap,
    VaultFee,
    VaultFeeMap,
    VaultReserveMap,
    OnChainIpfsVaultReportData,
)
from src.providers.consensus.types import PendingDeposit, Validator, ValidatorState, BlockDetailsResponse, BlockMessage, \
    BeaconBlockBody, ExecutionPayload, SyncAggregate, BlockHeaderFullResponse, BlockHeaderResponseData, BlockHeader, \
    BlockHeaderMessage
from src.types import EpochNumber, Gwei, SlotNumber, ValidatorIndex, ReferenceBlockStamp, StateRoot, BlockHash
from src.utils.units import gwei_to_wei
from src.web3py.types import Web3
from tests.utils.constants import HOODI_FORK_VERSION, MAINNET_FORK_VERSION


class TestStakingVaults:
    staking_vaults: StakingVaultsService

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
                reserve_ratio_bp=0,
                forced_rebalance_threshold_bp=0,
                infra_fee_bp=0,
                liquidity_fee_bp=0,
                reservation_fee_bp=0,
                pending_disconnect=False,
                mintable_st_eth=0,
            ),
            self.vault_adr_1: VaultInfo(
                vault=self.vault_adr_1,
                balance=Wei(0),
                in_out_delta=Wei(2000000000000000000),
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                liability_shares=490000000000000000,
                share_limit=0,
                reserve_ratio_bp=0,
                forced_rebalance_threshold_bp=0,
                infra_fee_bp=0,
                liquidity_fee_bp=0,
                reservation_fee_bp=0,
                pending_disconnect=False,
                mintable_st_eth=0,
            ),
            self.vault_adr_2: VaultInfo(
                vault=self.vault_adr_2,
                balance=Wei(2000900000000000000),
                in_out_delta=Wei(2000900000000000000),
                withdrawal_credentials='0x02000000000000000000000020d34fd0482e3bdc944952d0277a306860be0014',
                liability_shares=1200000000000010001,
                share_limit=0,
                reserve_ratio_bp=0,
                forced_rebalance_threshold_bp=0,
                infra_fee_bp=0,
                liquidity_fee_bp=0,
                reservation_fee_bp=0,
                pending_disconnect=False,
                mintable_st_eth=0,
            ),
            self.vault_adr_3: VaultInfo(
                vault=self.vault_adr_3,
                balance=Wei(1000000000000000000),
                in_out_delta=Wei(1000000000000000000),
                withdrawal_credentials='0x02000000000000000000000060b614c42d92d6c2e68af7f4b741867648abf9a4',
                liability_shares=0,
                share_limit=0,
                reserve_ratio_bp=0,
                forced_rebalance_threshold_bp=0,
                infra_fee_bp=0,
                liquidity_fee_bp=0,
                reservation_fee_bp=0,
                pending_disconnect=False,
                mintable_st_eth=0,
            ),
        }

        # --- Web3 Mock ---
        w3_mock = MagicMock()

        self.staking_vaults = StakingVaultsService(w3_mock)

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
        vaults_total_values = self.staking_vaults.get_vaults_total_values(
            self.vaults, validators, pending_deposits, MAINNET_FORK_VERSION
        )
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

        vaults_total_values = self.staking_vaults.get_vaults_total_values(
            self.vaults, validators, pending_deposits, MAINNET_FORK_VERSION
        )
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

        vaults_total_values = self.staking_vaults.get_vaults_total_values(
            self.vaults, validators, pending_deposits, HOODI_FORK_VERSION
        )
        expected = {
            self.vault_adr_0: 1000000000000000000,
            self.vault_adr_1: 0,
            self.vault_adr_2: 2000900000000000000,
            self.vault_adr_3: 1000000000000000000,
        }

        assert vaults_total_values == expected

    @pytest.mark.unit
    def test_calculate_pending_deposits(self):
        validators: list[Validator] = [
            Validator(
                index=ValidatorIndex(1986),
                balance=Gwei(1000000000),
                validator=ValidatorState(
                    pubkey='0xa5d9411ef615c74c9240634905d5ddd46dc40a87a09e8cc0332afddb246d291303e452a850917eefe09b3b8c70a307ce',
                    withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                    effective_balance=Gwei(1000000000),
                    slashed=False,
                    activation_eligibility_epoch=EpochNumber(226130),
                    activation_epoch=EpochNumber(226136),
                    exit_epoch=EpochNumber(227556),
                    withdrawable_epoch=EpochNumber(227812),
                ),
            )
        ]

        pending_deposits: list[PendingDeposit] = [
            # Valid deposit with correct withdrawal credentials
            PendingDeposit(
                pubkey='0xa5d9411ef615c74c9240634905d5ddd46dc40a87a09e8cc0332afddb246d291303e452a850917eefe09b3b8c70a307ce',
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                amount=Gwei(31000000000),
                signature='0xa8e06b7ad322e27b4aab71c9901f2196c288b9dd616aefbef9eb58084094ddc2e220cbec0024b563918f8ad18ad680ab062b7a09ec5a2287da5f1ef3ab9073f3c6287faaba714bb347958a0563f2aeaa4f7eb56cabeb29a063e964e93c1020db',
                slot=SlotNumber(259388),
            ),
        ]

        vaults_total_values = self.staking_vaults.get_vaults_total_values(
            self.vaults, validators, pending_deposits, HOODI_FORK_VERSION
        )
        expected = {
            self.vault_adr_0: 1000000000000000000,
            self.vault_adr_1: 32000000000000000000,
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

        vaults_total_values = self.staking_vaults.get_vaults_total_values(
            self.vaults, validators, pending_deposits, HOODI_FORK_VERSION
        )
        expected = {
            self.vault_adr_0: 1000000000000000000,
            self.vault_adr_1: 0,
            self.vault_adr_2: 2000900000000000000,
            self.vault_adr_3: 1000000000000000000,
        }
        assert vaults_total_values == expected

    @pytest.mark.unit
    def test_valid_signature_but_wrong_vault_withdrawal_credentials(self):
        valid_withdrawal_credentials = '0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc'

        deposit = PendingDeposit(
            pubkey='0x8f6ef94afaab1b6a693a4e65bcec154a2a285eb8e0aa7f9f8a8c596d4cf98cac8b981d77d1af0427dbaa5a37fab77b80',
            withdrawal_credentials=valid_withdrawal_credentials,
            amount=Gwei(1_000_000_000),
            signature='0xa8e06b7ad322e27b4aab71c9901f2196c288b9dd616aefbef9eb58084094ddc2e220cbec0024b563918f8ad18ad680ab062b7a09ec5a2287da5f1ef3ab9073f3c6287faaba714bb347958a0563f2aeaa4f7eb56cabeb29a063e964e93c1020db',
            slot=SlotNumber(259388),
        )

        # WC — different!
        vault_withdrawal_credentials = '0x0200000000000000000000001111111111111111111111111111111111111111'
        genesis_fork_version = '0x00000000'

        result = StakingVaultsService._get_valid_deposits_value(
            vault_withdrawal_credentials=vault_withdrawal_credentials,
            pubkey_deposits=[deposit],
            genesis_fork_version=genesis_fork_version
        )

        # THEN: valid signature, но WC не совпадает => return 0
        assert result == 0

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
    expected_liquidity_fee = Decimal('17007082495056342.0072967912')
    prev_fee = 22169367899378
    expected_total_fee = 27204382673365897  # 0.02720438267 ETH

    @pytest.mark.unit
    def test_fees(self):
        """
        Main purpose is check code behavior, not digits
        """
        vault1_adr = ChecksumAddress(HexAddress(HexStr("0xVault1")))
        vault2_adr = ChecksumAddress(HexAddress(HexStr("0xVault2")))
        vault3_adr = ChecksumAddress(HexAddress(HexStr("0xVault3")))
        vault4_adr = ChecksumAddress(HexAddress(HexStr("0xVault4")))
        vault5_adr = ChecksumAddress(HexAddress(HexStr("0xVault5")))
        vault6_adr = ChecksumAddress(HexAddress(HexStr("0xVault6")))

        prev_report_block_number = 0
        block_elapsed = 7_200

        mock_merkle_tree_data = StakingVaultIpfsReport(
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
                MerkleValue(
                    vault6_adr,  # address
                    MagicMock(),  # total_value_wei
                    123412,       # Must prove that prev fee didn't applied
                    MagicMock(),  # liability_shares
                    MagicMock(),  # slashing_reserve
                ),
            ],
            block_number=BlockNumber(prev_report_block_number),
            block_hash=MagicMock(),
            ref_slot=MagicMock(),
            timestamp=MagicMock(),
            prev_tree_cid=MagicMock(),
            extra_values={
                vault1_adr: ExtraValue(
                    in_out_delta=MagicMock(),
                    prev_fee=str(self.prev_fee),
                    infra_fee=MagicMock(),
                    liquidity_fee=MagicMock(),
                    reservation_fee=MagicMock(),
                ),
                vault6_adr: ExtraValue(
                    in_out_delta=MagicMock(),
                    prev_fee=str(123412),
                    infra_fee=MagicMock(),
                    liquidity_fee=MagicMock(),
                    reservation_fee=MagicMock(),
                ),
            },
        )

        vault1 = VaultInfo(
            vault=vault1_adr,
            liability_shares=self.liability_shares,
            reserve_ratio_bp=self.reserve_ratioBP,
            infra_fee_bp=self.infra_feeBP,
            liquidity_fee_bp=self.liquidity_feeBP,
            reservation_fee_bp=self.reservation_feeBP,
            mintable_st_eth=self.mintable_capacity_StETH,
            balance=MagicMock(),
            withdrawal_credentials=MagicMock(),
            share_limit=MagicMock(),
            forced_rebalance_threshold_bp=MagicMock(),
            pending_disconnect=MagicMock(),
            in_out_delta=MagicMock(),
        )

        vault2 = VaultInfo(
            vault=vault2_adr,
            liability_shares=self.liability_shares,
            reserve_ratio_bp=self.reserve_ratioBP,
            infra_fee_bp=self.infra_feeBP,
            liquidity_fee_bp=self.liquidity_feeBP,
            reservation_fee_bp=self.reservation_feeBP,
            mintable_st_eth=self.mintable_capacity_StETH,
            balance=MagicMock(),
            withdrawal_credentials=MagicMock(),
            share_limit=MagicMock(),
            forced_rebalance_threshold_bp=MagicMock(),
            pending_disconnect=MagicMock(),
            in_out_delta=MagicMock(),
        )

        vault3 = VaultInfo(
            vault=vault3_adr,
            liability_shares=self.liability_shares,
            reserve_ratio_bp=self.reserve_ratioBP,
            infra_fee_bp=self.infra_feeBP,
            liquidity_fee_bp=self.liquidity_feeBP,
            reservation_fee_bp=self.reservation_feeBP,
            mintable_st_eth=self.mintable_capacity_StETH,
            balance=MagicMock(),
            withdrawal_credentials=MagicMock(),
            share_limit=MagicMock(),
            forced_rebalance_threshold_bp=MagicMock(),
            pending_disconnect=MagicMock(),
            in_out_delta=MagicMock(),
        )

        vault4 = VaultInfo(
            vault=vault4_adr,
            liability_shares=self.liability_shares,
            reserve_ratio_bp=self.reserve_ratioBP,
            infra_fee_bp=self.infra_feeBP,
            liquidity_fee_bp=self.liquidity_feeBP,
            reservation_fee_bp=self.reservation_feeBP,
            mintable_st_eth=self.mintable_capacity_StETH,
            balance=MagicMock(),
            withdrawal_credentials=MagicMock(),
            share_limit=MagicMock(),
            forced_rebalance_threshold_bp=MagicMock(),
            pending_disconnect=MagicMock(),
            in_out_delta=MagicMock(),
        )

        vault5 = VaultInfo(
            vault=vault5_adr,
            liability_shares=self.liability_shares,
            reserve_ratio_bp=self.reserve_ratioBP,
            infra_fee_bp=self.infra_feeBP,
            liquidity_fee_bp=self.liquidity_feeBP,
            reservation_fee_bp=self.reservation_feeBP,
            mintable_st_eth=self.mintable_capacity_StETH,
            balance=MagicMock(),
            withdrawal_credentials=MagicMock(),
            share_limit=MagicMock(),
            forced_rebalance_threshold_bp=MagicMock(),
            pending_disconnect=MagicMock(),
            in_out_delta=MagicMock(),
        )

        vault6 = VaultInfo(
            vault=vault6_adr,
            # test for "reconnected event"
            # In past was reconnected and event and no further events
            # liability_shares must by 0 - cause no actions after reconnected event
            liability_shares=0,
            reserve_ratio_bp=self.reserve_ratioBP,
            infra_fee_bp=self.infra_feeBP,
            liquidity_fee_bp=self.liquidity_feeBP,
            reservation_fee_bp=self.reservation_feeBP,
            mintable_st_eth=self.mintable_capacity_StETH,
            balance=MagicMock(),
            withdrawal_credentials=MagicMock(),
            share_limit=MagicMock(),
            forced_rebalance_threshold_bp=MagicMock(),
            pending_disconnect=MagicMock(),
            in_out_delta=MagicMock(),
        )

        mock_prev_vault1 = copy.copy(vault1)
        mock_prev_vault1.liability_shares = 2879999910015672558976
        mock_prev_vault1.liquidity_fee_bp = 300

        mock_prev_vault2 = copy.copy(vault2)
        mock_prev_vault2.liability_shares = 2880000000000500000000
        mock_prev_vault2.liquidity_fee_bp = 300

        mock_prev_vault3 = copy.copy(vault3)
        mock_prev_vault3.liability_shares = 2880000000000000400000
        mock_prev_vault3.liquidity_fee_bp = 300

        mock_prev_vault4 = copy.copy(vault4)
        mock_prev_vault4.liability_shares = 2880000000000000200000
        mock_prev_vault4.liquidity_fee_bp = 300

        mock_prev_vault5 = copy.copy(vault5)
        mock_prev_vault5.liability_shares = 2879999999999999800000
        mock_prev_vault5.liquidity_fee_bp = 300

        mock_prev_vault6 = copy.copy(vault6)
        mock_prev_vault6.liability_shares = 0
        mock_prev_vault6.liquidity_fee_bp = 300

        mock_prev_vaults = [
            mock_prev_vault1,
            mock_prev_vault2,
            mock_prev_vault3,
            mock_prev_vault4,
            mock_prev_vault5
        ]

        vaults_total_values: VaultTotalValueMap = {
            ChecksumAddress(HexAddress(HexStr(vault1_adr))): self.vault_total_value,
            ChecksumAddress(HexAddress(HexStr(vault2_adr))): self.vault_total_value,
            ChecksumAddress(HexAddress(HexStr(vault3_adr))): self.vault_total_value,
            ChecksumAddress(HexAddress(HexStr(vault4_adr))): self.vault_total_value,
            ChecksumAddress(HexAddress(HexStr(vault5_adr))): self.vault_total_value,
            ChecksumAddress(HexAddress(HexStr(vault6_adr))): self.vault_total_value,
        }

        vaults = {
            vault6.vault: vault6,
            vault1.vault: vault1,
            vault2.vault: vault2,
            vault3.vault: vault3,
            vault4.vault: vault4,
            vault5.vault: vault5,

        }

        vaults_fee_updated_events = [
            VaultFeesUpdatedEvent(
                block_number=BlockNumber(3201),
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
                block_number=BlockNumber(3701),
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
                vault=vault1_adr,
                block_number=BlockNumber(3601),
                amount_of_shares=8_998_437_744_1024,
                locked_amount=MagicMock(),
                event=MagicMock(),
                log_index=MagicMock(),
                transaction_index=MagicMock(),
                address=MagicMock(),
                transaction_hash=MagicMock(),
                block_hash=MagicMock(),
            )
        ]

        vault_rebalance_events = [
            VaultRebalancedEvent(
                vault=vault2_adr,
                block_number=BlockNumber(3601),
                shares_burned=500_000_000,
                ether_withdrawn=MagicMock(),
                event=MagicMock(),
                log_index=MagicMock(),
                transaction_index=MagicMock(),
                address=MagicMock(),
                transaction_hash=MagicMock(),
                block_hash=MagicMock(),
            )
        ]

        written_off_to_be_internalized_events = [
            BadDebtWrittenOffToBeInternalizedEvent(
                vault=vault3_adr,
                block_number=BlockNumber(3601),
                bad_debt_shares=400_000,
                event=MagicMock(),
                log_index=MagicMock(),
                transaction_index=MagicMock(),
                address=MagicMock(),
                transaction_hash=MagicMock(),
                block_hash=MagicMock(),
            )
        ]

        bad_debt_socialized_events = [
            BadDebtSocializedEvent(
                vault_donor=vault4_adr,
                vault_acceptor=vault5_adr,
                block_number=BlockNumber(3601),
                bad_debt_shares=400_000,
                event=MagicMock(),
                log_index=MagicMock(),
                transaction_index=MagicMock(),
                address=MagicMock(),
                transaction_hash=MagicMock(),
                block_hash=MagicMock(),
            ),
            BadDebtSocializedEvent(
                vault_donor=vault5_adr,
                vault_acceptor=vault4_adr,
                block_number=BlockNumber(3501),
                bad_debt_shares=200_000,
                event=MagicMock(),
                log_index=MagicMock(),
                transaction_index=MagicMock(),
                address=MagicMock(),
                transaction_hash=MagicMock(),
                block_hash=MagicMock(),
            )
        ]

        vault_connected_events = [
            VaultConnectedEvent(
                vault=vault6_adr,
                share_limit=MagicMock(),
                reserve_ratio_bp=MagicMock(),
                forced_rebalance_threshold_bp=MagicMock(),
                infra_fee_bp=MagicMock(),
                liquidity_fee_bp=MagicMock(),
                reservation_fee_bp=MagicMock(),
                block_number=BlockNumber(3501),
                event=MagicMock(),
                log_index=MagicMock(),
                transaction_index=MagicMock(),
                address=MagicMock(),
                transaction_hash=MagicMock(),
                block_hash=MagicMock(),
            )
        ]

        mock_prev_ipfs_report_cid = OnChainIpfsVaultReportData(
            timestamp=MagicMock(),
            tree_root=MagicMock(),
            report_cid="report_cid", # for getting prev report data
        )

        # --- Web3 Mock ---
        w3_mock = MagicMock()
        lazy_oracle_mock = MagicMock()
        vault_hub_mock = MagicMock()
        chain_config_mock = MagicMock()
        frame_mock = MagicMock()

        lazy_oracle_mock.get_all_vaults = MagicMock(return_value=mock_prev_vaults)
        vault_hub_mock.get_vault_fee_updated_events = MagicMock(return_value=vaults_fee_updated_events)
        vault_hub_mock.get_minted_events = MagicMock(return_value=minted_shares_events)
        vault_hub_mock.get_burned_events = MagicMock(return_value=burned_shares_events)

        vault_hub_mock.get_vault_rebalanced_events = MagicMock(return_value=vault_rebalance_events)
        vault_hub_mock.get_bad_debt_socialized_events = MagicMock(return_value=bad_debt_socialized_events)
        vault_hub_mock.get_bad_debt_written_off_to_be_internalized_events = MagicMock(return_value=written_off_to_be_internalized_events)
        vault_hub_mock.get_vault_connected_events = MagicMock(return_value=vault_connected_events)

        w3_mock.lido_contracts.lazy_oracle = lazy_oracle_mock
        w3_mock.lido_contracts.vault_hub = vault_hub_mock

        # cc_mock, ipfs_client, lido_mock, vault_hub_mock, lazy_oracle_mock, account_oracle_mock
        self.staking_vaults = StakingVaultsService(w3_mock)

        # Note: when we have prev report - all events on that block are already included in prev report.
        # We shift the starting point by one block forward.
        # This's synthetic but closely to real situation
        started_block_for_calculation = prev_report_block_number + 1
        self.staking_vaults._get_start_point_for_fee_calculations = MagicMock(
            return_value=[mock_merkle_tree_data, started_block_for_calculation, MagicMock()]
        )

        mock_ref_block = MagicMock()
        mock_ref_block.block_number = started_block_for_calculation + block_elapsed
        expected_destination_block = mock_ref_block.block_number

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
            ),
            vault2_adr: VaultFee(
                infra_fee=2907180231545765,
                liquidity_fee=20513697696886690,
                reservation_fee=7267950578864411,
                prev_fee=0
            ),
            vault3_adr: VaultFee(
                infra_fee=2907180231545765,
                liquidity_fee=20513697696884910,
                reservation_fee=7267950578864411,
                prev_fee=0
            ),
            vault4_adr: VaultFee(
                infra_fee=2907180231545765,
                liquidity_fee=20513697696884910,
                reservation_fee=7267950578864411,
                prev_fee=0
            ),
            vault5_adr: VaultFee(
                infra_fee=2907180231545765,
                liquidity_fee=20513697696884908,
                reservation_fee=7267950578864411,
                prev_fee=0
            ),
            vault6_adr: VaultFee(
                infra_fee=2907180231545765,
                liquidity_fee=0,
                reservation_fee=7267950578864411,
                prev_fee=0
            )
        }

        # That's proof and check that we fetch events from prev_report_number + 1
        vault_hub_mock.get_vault_fee_updated_events.assert_called_once_with(started_block_for_calculation, expected_destination_block)
        vault_hub_mock.get_minted_events.assert_called_once_with(started_block_for_calculation, expected_destination_block)
        vault_hub_mock.get_burned_events.assert_called_once_with(started_block_for_calculation, expected_destination_block)
        vault_hub_mock.get_vault_rebalanced_events.assert_called_once_with(started_block_for_calculation, expected_destination_block)
        vault_hub_mock.get_bad_debt_socialized_events.assert_called_once_with(started_block_for_calculation, expected_destination_block)
        vault_hub_mock.get_bad_debt_written_off_to_be_internalized_events.assert_called_once_with(started_block_for_calculation, expected_destination_block)
        vault_hub_mock.get_vault_connected_events.assert_called_once_with(started_block_for_calculation, expected_destination_block)

        assert self.expected_total_fee == expected_fees[vault1_adr].total()
        assert actual_fees[ChecksumAddress(HexAddress(HexStr(vault1_adr)))].total() == expected_fees[vault1_adr].total()
        assert actual_fees == expected_fees

    @pytest.mark.unit
    def test_calc_liquidity_fee_raises_if_connected_with_non_zero_fee(self):
        vault_address = "0xVault123"

        pre_total_pooled_ether = Wei(1_000_000_000_000_000_000_000)
        pre_total_shares = 1_000_000_000_000_000_000_000
        core_apr_ratio = Decimal("0.10")

        prev_block = BlockNumber(100)
        current_block = BlockNumber(110)
        liquidity_fee_bp = 100  # 1%

        minted_shares = 1_000_000
        # TIP: specially wrong value. Could not greater than shares in minted event
        wrong_shares = 10_000_000

        minted_event = MintedSharesOnVaultEvent(
            vault=vault_address,
            block_number=BlockNumber(105),
            amount_of_shares=minted_shares,
            locked_amount=MagicMock(),
            event=MagicMock(),
            log_index=MagicMock(),
            transaction_index=MagicMock(),
            address=MagicMock(),
            transaction_hash=MagicMock(),
            block_hash=MagicMock(),
        )

        connected_event = VaultConnectedEvent(
            vault=vault_address,
            share_limit=MagicMock(),
            reserve_ratio_bp=MagicMock(),
            forced_rebalance_threshold_bp=MagicMock(),
            infra_fee_bp=MagicMock(),
            liquidity_fee_bp=MagicMock(),
            reservation_fee_bp=MagicMock(),
            block_number=BlockNumber(101),
            event=MagicMock(),
            log_index=MagicMock(),
            transaction_index=MagicMock(),
            address=MagicMock(),
            transaction_hash=MagicMock(),
            block_hash=MagicMock(),
        )

        events: defaultdict[str, list[VaultEventType]] = defaultdict(list)
        events[vault_address] = [minted_event, connected_event]

        with pytest.raises(ValueError, match=r"Wrong vault liquidity shares by vault .* got .*"):
            StakingVaultsService.calc_liquidity_fee(
                vault_address=vault_address,
                liability_shares=wrong_shares,
                liquidity_fee_bp=liquidity_fee_bp,
                events=events,
                prev_block_number=prev_block,
                current_block=current_block,
                pre_total_pooled_ether=pre_total_pooled_ether,
                pre_total_shares=pre_total_shares,
                core_apr_ratio=core_apr_ratio,
            )

    @pytest.mark.unit
    def test_fees_raises_if_liability_shares_mismatch(self):
        vault1_adr = ChecksumAddress(HexAddress(HexStr("0xVault1")))
        prev_block_number = 0
        block_elapsed = 7200

        mock_merkle_tree_data = StakingVaultIpfsReport(
            format="v1",
            leaf_encoding=["encoding1"],
            tree=["node1"],
            values=[
                MerkleValue(
                    vault_address=vault1_adr,
                    total_value_wei=Wei(0),
                    fee=1000,
                    liability_shares=123456789,  # << prev value. Raises Error
                    slashing_reserve=0,
                )
            ],
            block_number=BlockNumber(prev_block_number),
            block_hash=MagicMock(),
            ref_slot=MagicMock(),
            timestamp=MagicMock(),
            prev_tree_cid=MagicMock(),
            extra_values={
                vault1_adr: ExtraValue(
                    in_out_delta="0",
                    prev_fee="1000",
                    infra_fee="0",
                    liquidity_fee="0",
                    reservation_fee="0",
                )
            },
        )

        vault1 = VaultInfo(
            vault=vault1_adr,
            liability_shares=999999999,  # << отличие
            reserve_ratio_bp=0,
            infra_fee_bp=0,
            liquidity_fee_bp=0,
            reservation_fee_bp=0,
            mintable_st_eth=0,
            balance=Wei(0),
            withdrawal_credentials="0x0",
            share_limit=0,
            forced_rebalance_threshold_bp=0,
            pending_disconnect=False,
            in_out_delta=Wei(0),
        )

        vaults_total_values = {vault1_adr: 0}
        vaults = {vault1_adr: vault1}

        mock_prev_ipfs_report_cid = MagicMock()

        w3_mock = MagicMock()
        lazy_oracle_mock = MagicMock()
        vault_hub_mock = MagicMock()

        vault_hub_mock.get_vault_fee_updated_events = MagicMock(return_value=[])
        vault_hub_mock.get_minted_events = MagicMock(return_value=[])
        vault_hub_mock.get_burned_events = MagicMock(return_value=[])
        vault_hub_mock.get_vault_rebalanced_events = MagicMock(return_value=[])
        vault_hub_mock.get_bad_debt_socialized_events = MagicMock(return_value=[])
        vault_hub_mock.get_bad_debt_written_off_to_be_internalized_events = MagicMock(return_value=[])
        vault_hub_mock.get_vault_connected_events = MagicMock(return_value=[])

        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.lazy_oracle = lazy_oracle_mock

        staking_vaults = StakingVaultsService(w3_mock)

        staking_vaults._get_start_point_for_fee_calculations = MagicMock(
            return_value=[mock_merkle_tree_data, prev_block_number, MagicMock()]
        )

        mock_ref_block = MagicMock()
        mock_ref_block.block_number = prev_block_number + block_elapsed

        with pytest.raises(ValueError, match="Wrong liability shares by vault"):
            staking_vaults.get_vaults_fees(
                blockstamp=mock_ref_block,
                vaults=vaults,
                vaults_total_values=vaults_total_values,
                latest_onchain_ipfs_report_data=mock_prev_ipfs_report_cid,
                core_apr_ratio=Decimal(0.3),
                pre_total_pooled_ether=1,
                pre_total_shares=1,
                chain_config=MagicMock(),
                frame_config=MagicMock(),
            )

    @pytest.mark.parametrize(
        "vault_total_value, block_elapsed, core_apr_ratio, infra_fee_bp, expected_wei",
        [
            (vault_total_value, 7_200, core_ratio_apr, infra_feeBP, expected_infra_fee),
            (vault_total_value, 7_200 * 364, core_ratio_apr, infra_feeBP, Decimal('1058213604282658229.86386748')),
        ],
    )
    def test_infra_fee(self, vault_total_value, block_elapsed, core_apr_ratio, infra_fee_bp, expected_wei):
        result = StakingVaultsService.calc_fee_value(
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
    def test_reservation_liquidity_fee(
        self, mintable_capacity_steth, block_elapsed, core_apr_ratio, reservation_fee_bp, expected_wei
    ):
        result = StakingVaultsService.calc_fee_value(
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
                        block_number=BlockNumber(3600),
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
                        block_number=BlockNumber(3700),
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
                        block_number=BlockNumber(3200),
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
            BlockNumber(0),  # prev_block_number
            BlockNumber(7_200),  # current_block
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
        result = StakingVaultsService.calc_liquidity_fee(
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

    @pytest.mark.unit
    def test_slashing_reserver(self):
        mock_ref_epoch = EpochNumber(40_000)

        ref_block_stamp = ReferenceBlockStamp(
            state_root=MagicMock(),
            slot_number=MagicMock(),
            block_hash=MagicMock(),
            block_number=MagicMock(),
            block_timestamp=MagicMock(),
            ref_slot=MagicMock(),
            ref_epoch=mock_ref_epoch,
        )

        # VaultsMap
        vault_address_1 = ChecksumAddress(HexAddress(HexStr("0x1234567890abcdef1234567890abcdef12345678")))
        vault_address_2 = ChecksumAddress(HexAddress(HexStr("0x2222222222222222222222222222222222222222")))
        vault_address_3 = ChecksumAddress(HexAddress(HexStr("0x3333333333333333333333333333333333333333")))
        vault_address_4 = ChecksumAddress(HexAddress(HexStr("0x4444444444444444444444444444444444444444")))
        withdrawal_credentials_1 = "withdrawal_credentials_1"
        withdrawal_credentials_2 = "withdrawal_credentials_2"
        withdrawal_credentials_3 = "withdrawal_credentials_3"
        withdrawal_credentials_4 = "withdrawal_credentials_4"
        vaults_map = {
            vault_address_1: VaultInfo(
                vault=vault_address_1,
                balance=MagicMock(),
                withdrawal_credentials=withdrawal_credentials_1,
                liability_shares=MagicMock(),
                share_limit=MagicMock(),
                reserve_ratio_bp=650,
                forced_rebalance_threshold_bp=MagicMock(),
                infra_fee_bp=MagicMock(),
                liquidity_fee_bp=MagicMock(),
                reservation_fee_bp=MagicMock(),
                pending_disconnect=MagicMock(),
                mintable_st_eth=MagicMock(),
                in_out_delta=MagicMock(),
            ),
            vault_address_2: VaultInfo(
                vault=vault_address_2,
                balance=MagicMock(),
                withdrawal_credentials=withdrawal_credentials_2,
                liability_shares=MagicMock(),
                share_limit=MagicMock(),
                reserve_ratio_bp=650,
                forced_rebalance_threshold_bp=MagicMock(),
                infra_fee_bp=MagicMock(),
                liquidity_fee_bp=MagicMock(),
                reservation_fee_bp=MagicMock(),
                pending_disconnect=MagicMock(),
                mintable_st_eth=MagicMock(),
                in_out_delta=MagicMock(),
            ),
            vault_address_3: VaultInfo(
                vault=vault_address_3,
                balance=MagicMock(),
                withdrawal_credentials=withdrawal_credentials_3,
                liability_shares=MagicMock(),
                share_limit=MagicMock(),
                reserve_ratio_bp=650,
                forced_rebalance_threshold_bp=MagicMock(),
                infra_fee_bp=MagicMock(),
                liquidity_fee_bp=MagicMock(),
                reservation_fee_bp=MagicMock(),
                pending_disconnect=MagicMock(),
                mintable_st_eth=MagicMock(),
                in_out_delta=MagicMock(),
            ),
            vault_address_4: VaultInfo(
                vault=vault_address_4,
                balance=MagicMock(),
                withdrawal_credentials=withdrawal_credentials_4,
                liability_shares=MagicMock(),
                share_limit=MagicMock(),
                reserve_ratio_bp=650,
                forced_rebalance_threshold_bp=MagicMock(),
                infra_fee_bp=MagicMock(),
                liquidity_fee_bp=MagicMock(),
                reservation_fee_bp=MagicMock(),
                pending_disconnect=MagicMock(),
                mintable_st_eth=MagicMock(),
                in_out_delta=MagicMock(),
            ),
        }

        # Validator
        validator_1 = Validator(
            index=ValidatorIndex(1),
            balance=Gwei(32_000_000_000),
            validator=ValidatorState(
                pubkey=MagicMock(),
                withdrawal_credentials=withdrawal_credentials_1,
                effective_balance=MagicMock(),
                slashed=True,
                activation_eligibility_epoch=MagicMock(),
                activation_epoch=MagicMock(),
                exit_epoch=MagicMock(),
                withdrawable_epoch=mock_ref_epoch,
            )
        )
        validator_2 = Validator(
            index=ValidatorIndex(2),
            balance=Gwei(64_000_000_000),
            validator=ValidatorState(
                pubkey=MagicMock(),
                withdrawal_credentials=withdrawal_credentials_2,
                effective_balance=MagicMock(),
                slashed=True,
                activation_eligibility_epoch=MagicMock(),
                activation_epoch=MagicMock(),
                exit_epoch=MagicMock(),
                withdrawable_epoch=EpochNumber(50_000),
            ),
        )
        validator_3 = Validator(
            index=ValidatorIndex(3),
            balance=Gwei(64_000_000_000),
            validator=ValidatorState(
                pubkey=MagicMock(),
                withdrawal_credentials=withdrawal_credentials_3,
                effective_balance=MagicMock(),
                slashed=False,
                activation_eligibility_epoch=MagicMock(),
                activation_epoch=MagicMock(),
                exit_epoch=MagicMock(),
                withdrawable_epoch=MagicMock(),
            ),
        )
        validator_4 = Validator(
            index=ValidatorIndex(3),
            balance=Gwei(64_000_000_000),
            validator=ValidatorState(
                pubkey=MagicMock(),
                withdrawal_credentials=withdrawal_credentials_3,
                effective_balance=MagicMock(),
                slashed=True,
                activation_eligibility_epoch=MagicMock(),
                activation_epoch=MagicMock(),
                exit_epoch=MagicMock(),
                withdrawable_epoch=EpochNumber(25_000),
            ),
        )
        validators = [validator_1, validator_2, validator_3, validator_4]

        # ChainConfig
        chain_config = ChainConfig(
            slots_per_epoch=32,
            seconds_per_slot=MagicMock(),
            genesis_time=MagicMock(),
        )

        # --- Web3 Mock ---
        w3_mock = MagicMock()

        # oracle_daemon_config mock with left/right shifts
        oracle_daemon_config_mock = MagicMock()
        oracle_daemon_config_mock.slashing_reserve_we_left_shift = MagicMock(return_value=8192)
        oracle_daemon_config_mock.slashing_reserve_we_right_shift = MagicMock(return_value=8192)

        cc_mock = MagicMock()
        cc_mock.get_validator_state = MagicMock(
            return_value=validator_1
        )

        w3_mock.lido_contracts.oracle_daemon_config = oracle_daemon_config_mock
        w3_mock.cc = cc_mock

        self.staking_vaults = StakingVaultsService(w3_mock)
        result = self.staking_vaults.get_vaults_slashing_reserve(
            ref_block_stamp,
            vaults_map,
            validators,
            chain_config
        )

        expected_reserve_1 = Decimal(gwei_to_wei(validator_1.balance)) * Decimal(vaults_map[vault_address_1].reserve_ratio_bp) / Decimal(TOTAL_BASIS_POINTS)
        expected_reserve_1 = int(expected_reserve_1.to_integral_value(ROUND_UP))

        expected_reserve_2 = Decimal(gwei_to_wei(validator_2.balance)) * Decimal(
            vaults_map[vault_address_2].reserve_ratio_bp) / Decimal(TOTAL_BASIS_POINTS)
        expected_reserve_2 = int(expected_reserve_2.to_integral_value(ROUND_UP))

        assert expected_reserve_1 == 2080000000000000000
        assert expected_reserve_2 == 4160000000000000000
        expected = {
            vault_address_1: expected_reserve_1,
            vault_address_2: expected_reserve_2,
        }

        assert result == expected

    @pytest.mark.unit
    def test_build_tree_happy_path(self):
        vault_address = ChecksumAddress(HexAddress(HexStr("0x1234567890abcdef1234567890abcdef12345678")))

        vault_info = VaultInfo(
            vault=vault_address,
            balance=MagicMock(),
            withdrawal_credentials=MagicMock(),
            liability_shares=2880 * 10**18,
            share_limit=MagicMock(),
            reserve_ratio_bp=MagicMock(),
            forced_rebalance_threshold_bp=MagicMock(),
            infra_fee_bp=MagicMock(),
            liquidity_fee_bp=MagicMock(),
            reservation_fee_bp=MagicMock(),
            pending_disconnect=MagicMock(),
            mintable_st_eth=MagicMock(),
            in_out_delta=Wei(1_234_567_890_000_000_000)
        )

        vaults: VaultsMap = {
            vault_address: vault_info
        }

        total_value = 1_000_000_000_000_000_000  # 1 ETH
        vaults_total_values: VaultTotalValueMap = {
            vault_address: total_value
        }

        vault_fee = VaultFee(
            infra_fee=100,
            liquidity_fee=200,
            reservation_fee=300,
            prev_fee=400,
        )
        vaults_fees: VaultFeeMap = {
            vault_address: vault_fee
        }

        slashing_reserve_mock = 5555
        vaults_slashing_reserve: VaultReserveMap = {
            vault_address: slashing_reserve_mock
        }

        tree_data = StakingVaultsService.build_tree_data(
            vaults,
            vaults_total_values,
            vaults_fees,
            vaults_slashing_reserve,
        )

        fees = 1000
        expected_tree_data = [(vault_address, total_value, fees, vault_info.liability_shares, slashing_reserve_mock)]
        assert tree_data == expected_tree_data

        # --- Web3 Mock ---
        ipfs_mock = MagicMock()
        expected_cid = "QmMockCID123"
        ipfs_mock.publish.return_value = expected_cid

        # Web3 mock with IPFS
        w3_mock = MagicMock()
        w3_mock.ipfs = ipfs_mock

        staking_vaults = StakingVaultsService(w3_mock)
        merkle_tree = staking_vaults.get_merkle_tree(tree_data)
        expected_merkle_tree = '0xde6252c90afeb175b7e788655811eece8e7e11943e36377a775279479d30bcee'
        assert expected_merkle_tree == f'0x{merkle_tree.root.hex()}'

        bs = ReferenceBlockStamp(
            state_root=MagicMock(),
            slot_number=SlotNumber(123456),
            block_hash=BlockHash(HexStr("0xabc123")),
            block_number=BlockNumber(789654),
            block_timestamp=MagicMock(),
            ref_slot=SlotNumber(123450),
            ref_epoch=MagicMock(),
        )

        prev_tree_cid = 'prev_tree_cid'

        chain_config = ChainConfig(
            slots_per_epoch=MagicMock(),
            seconds_per_slot=12,
            genesis_time=1_600_000_000
        )

        dumped_tree = staking_vaults.get_dumped_tree(
            tree=merkle_tree,
            vaults=vaults,
            bs=bs,
            prev_tree_cid=prev_tree_cid,
            chain_config=chain_config,
            vaults_fee_map=vaults_fees
        )

        expected_dumped_tree = {
            'format': 'standard-v1',
            'leafEncoding': ('address', 'uint256', 'uint256', 'uint256', 'uint256'),
            'tree': (b'\xdebR\xc9\n\xfe\xb1u\xb7\xe7\x88eX\x11\xee\xce\x8e~\x11\x94>67z'
                     b'wRyG\x9d0\xbc\xee',),
            'blockHash': '0xabc123',
            'blockNumber': bs.block_number,
            'prevTreeCID': 'prev_tree_cid',
            'refSlot': bs.ref_slot,
            'timestamp': 1601481472,
            'values': [
                {
                    'treeIndex': 0,
                    'value': (
                        vault_address,
                        str(vaults_total_values[vault_address]),
                        str(fees),
                        str(vault_info.liability_shares),
                        str(vaults_slashing_reserve[vault_address])
                    )
                }
            ],
            'extraValues': {
                vault_address: {
                    'inOutDelta': str(vault_info.in_out_delta),
                    'infraFee': str(vaults_fees[vault_address].infra_fee),
                    'liquidityFee': str(vaults_fees[vault_address].liquidity_fee),
                    'prevFee': str(vaults_fees[vault_address].prev_fee),
                    'reservationFee': str(vaults_fees[vault_address].reservation_fee),
                }
            },
            'leafIndexToData': {
                'fee': 2,
                'liabilityShares': 3,
                'slashingReserve': 4,
                'totalValueWei': 1,
                'vaultAddress': 0
            }
        }

        assert dumped_tree == expected_dumped_tree

        cid = staking_vaults.publish_tree(
            tree=merkle_tree,
            vaults=vaults,
            bs=bs,
            prev_tree_cid=prev_tree_cid,
            chain_config=chain_config,
            vaults_fee_map=vaults_fees
        )

        dumped_tree_str = json.dumps(dumped_tree, default=StakingVaultsService.tree_encoder)
        print(dumped_tree_str)

        ipfs_mock.publish.assert_called_with(
            dumped_tree_str.encode('utf-8'),
            "merkle_tree.json"
        )

        assert cid == expected_cid

    @pytest.mark.unit
    def test_build_tree_empty_total_value(self):
        vault_address = ChecksumAddress(HexAddress(HexStr("0x1234567890abcdef1234567890abcdef12345678")))

        vault_info = VaultInfo(
            vault=vault_address,
            balance=MagicMock(),
            withdrawal_credentials=MagicMock(),
            liability_shares=2880 * 10**18,
            share_limit=MagicMock(),
            reserve_ratio_bp=MagicMock(),
            forced_rebalance_threshold_bp=MagicMock(),
            infra_fee_bp=MagicMock(),
            liquidity_fee_bp=MagicMock(),
            reservation_fee_bp=MagicMock(),
            pending_disconnect=MagicMock(),
            mintable_st_eth=MagicMock(),
            in_out_delta=MagicMock(),
        )

        vaults: VaultsMap = {
            vault_address: vault_info
        }

        total_value = 1_000_000_000_000_000_000  # 1 ETH
        vaults_total_values: VaultTotalValueMap = {
            ChecksumAddress(HexAddress(HexStr("0xanother_vault_address_rauses_errror"))): total_value
        }

        vaults_slashing_reserve: VaultReserveMap = {}
        vaults_fees: VaultFeeMap = {}

        with pytest.raises(ValueError, match=f"Vault {vault_address} is not in total_values"):
            StakingVaultsService.build_tree_data(vaults, vaults_total_values, vaults_fees, vaults_slashing_reserve)

    @pytest.mark.unit
    def test_build_tree_empty_vaults_fees(self):
        vault_address = ChecksumAddress(HexAddress(HexStr("0x1234567890abcdef1234567890abcdef12345678")))

        vault_info = VaultInfo(
            vault=vault_address,
            balance=MagicMock(),
            withdrawal_credentials=MagicMock(),
            liability_shares=2880 * 10 ** 18,
            share_limit=MagicMock(),
            reserve_ratio_bp=MagicMock(),
            forced_rebalance_threshold_bp=MagicMock(),
            infra_fee_bp=MagicMock(),
            liquidity_fee_bp=MagicMock(),
            reservation_fee_bp=MagicMock(),
            pending_disconnect=MagicMock(),
            mintable_st_eth=MagicMock(),
            in_out_delta=MagicMock(),
        )

        vaults: VaultsMap = {
            vault_address: vault_info
        }

        total_value = 1_000_000_000_000_000_000  # 1 ETH
        vaults_total_values: VaultTotalValueMap = {
            vault_address: total_value
        }

        vault_fee = VaultFee(
            infra_fee=100,
            liquidity_fee=200,
            reservation_fee=300,
            prev_fee=400,
        )
        vaults_fees: VaultFeeMap = {
            ChecksumAddress(HexAddress(HexStr("0xanother_vault_address_rauses_errror"))): vault_fee
        }

        vaults_slashing_reserve: VaultReserveMap = {
            vault_address: 5555
        }

        with pytest.raises(ValueError, match=f"Vault {vault_address} is not in vaults_fees"):
            StakingVaultsService.build_tree_data(vaults, vaults_total_values, vaults_fees, vaults_slashing_reserve)

    @pytest.mark.unit
    def test_tree_encoder(self):
        # tree_encoder_bytes
        b = b"\x12\x34"
        result = StakingVaultsService.tree_encoder(b)
        assert result == "0x1234"

        # tree_encoder_cid:
        cid= CID("cid12345")
        result = StakingVaultsService.tree_encoder(cid)
        assert result == "cid12345"

        bs = ReferenceBlockStamp(
            state_root=StateRoot(HexStr("state_root")),
            slot_number=SlotNumber(123456),
            block_hash=BlockHash(HexStr("0xabc123")),
            block_number=BlockNumber(789654),
            block_timestamp=Timestamp(1234),
            ref_slot=SlotNumber(123450),
            ref_epoch=EpochNumber(123451),
        )

        result = StakingVaultsService.tree_encoder(bs)
        assert result == {
            'block_hash': '0xabc123',
            'block_number': 789654,
            'block_timestamp': 1234,
            'ref_epoch': 123451,
            'ref_slot': 123450,
            'slot_number': 123456,
            'state_root': 'state_root'
        }

        # tree_encoder_invalid_type:
        with pytest.raises(TypeError, match="Object of type <class 'int'> is not JSON serializable"):
           StakingVaultsService.tree_encoder(42)

    @pytest.mark.unit
    def test_get_ipfs_report(self):
        w3_mock = MagicMock()
        mock_fetched_bytes = (b'{"format": "standard-v1", "leafEncoding": ["address", "uint256", "uint256", "uint256", '
                              b'"int256"], "tree": ['
                              b'"0xde6252c90afeb175b7e788655811eece8e7e11943e36377a775279479d30bcee"], "values": [{'
                              b'"value": ["0x1234567890abcdef1234567890abcdef12345678", "1000000000000000000", '
                              b'"1000", "2880000000000000000000", "5555"], "treeIndex": 0}], "refSlot": 123450, '
                              b'"blockHash": "0xabc123", "blockNumber": 789654, "timestamp": 1601481472, '
                              b'"extraValues": {"0x1234567890abcdef1234567890abcdef12345678": {"inOutDelta": '
                              b'"1234567890000000000", "prevFee": "400", "infraFee": "100", "liquidityFee": "200", '
                              b'"reservationFee": "300"}}, "prevTreeCID": "prev_tree_cid", "leafIndexToData": {'
                              b'"vaultAddress": 0, "totalValueWei": 1, "fee": 2, "liabilityShares": 3, '
                              b'"slashingReserve": 4}}')
        w3_mock.ipfs.fetch.return_value = mock_fetched_bytes

        staking_vaults = StakingVaultsService(w3_mock)
        test_cid = "QmMockCID123"
        result = staking_vaults.get_ipfs_report(test_cid)

        assert result.tree[0] == '0xde6252c90afeb175b7e788655811eece8e7e11943e36377a775279479d30bcee'

        with pytest.raises(ValueError, match="Arg ipfs_report_cid could not be ''"):
            staking_vaults.get_ipfs_report('')

    @pytest.mark.unit
    def test_get_start_point_happy_path_with_valid_ipfs(self):
        web3 = MagicMock()
        web3.cc.get_block_header.return_value = BlockHeaderFullResponse(
            execution_optimistic=MagicMock(),
            data=BlockHeaderResponseData(
                root=MagicMock(),
                canonical=MagicMock(),
                header=BlockHeader(
                    message=BlockHeaderMessage(
                        slot=SlotNumber(10_000),
                        proposer_index=MagicMock(),
                        parent_root=MagicMock(),
                        state_root=MagicMock(),
                        body_root=MagicMock(),
                    ),
                    signature=MagicMock(),
                ),
            ),
            finalized=True
        )

        expected_block_hash = BlockHash(HexStr("0x0abc1234def56789abc01234def0abcd12345678"))
        ref_block_number = BlockNumber(5_000)
        expected_block_number = ref_block_number + 1
        web3.cc.get_block_details.return_value = BlockDetailsResponse(
            message=BlockMessage(
                slot=MagicMock(),
                proposer_index=MagicMock(),
                parent_root=MagicMock(),
                state_root=MagicMock(),
                body=BeaconBlockBody(
                    execution_payload=ExecutionPayload(
                        parent_hash=MagicMock(),
                        block_number=ref_block_number,
                        timestamp=MagicMock(),
                        block_hash=expected_block_hash,
                    ),
                    attestations=MagicMock(),
                    sync_aggregate=SyncAggregate(
                        sync_committee_bits=MagicMock(),
                    ),
                ),
            ),
            signature=MagicMock(),
        )

        staking_vaults = StakingVaultsService(w3=web3)

        blockstamp = ReferenceBlockStamp(
            state_root=StateRoot(HexStr("0xabcabc")),
            slot_number=SlotNumber(1234),
            block_hash=BlockHash(HexStr("0xdeadbeef")),
            block_number=BlockNumber(4321),
            block_timestamp=Timestamp(1690000000),
            ref_slot=SlotNumber(1230),
            ref_epoch=EpochNumber(40),
        )

        ipfs_data = OnChainIpfsVaultReportData(
            timestamp=1690000100,
            tree_root=b'\xab\xcd\xef',
            report_cid="cid123"
        )

        frame_config = FrameConfig(
            initial_epoch=10,
            epochs_per_frame=2,
            fast_lane_length_slots=16
        )

        chain_config = ChainConfig(
            slots_per_epoch=32,
            seconds_per_slot=12,
            genesis_time=1600000000
        )

        # previous report mocked
        expected_report_root = "0xabcdef"
        prev_report = StakingVaultIpfsReport(
            format=MagicMock(),
            leaf_encoding=MagicMock(),
            tree=[
                expected_report_root
            ],
            values=MagicMock(),
            ref_slot=MagicMock(),
            block_number=MagicMock(),
            block_hash=MagicMock(),
            timestamp=MagicMock(),
            prev_tree_cid=MagicMock(),
            extra_values=MagicMock(),
        )

        # get_ipfs_report returns prev_report
        staking_vaults.get_ipfs_report = MagicMock(return_value=prev_report)
        staking_vaults.is_tree_root_valid = MagicMock(return_value=True)
        staking_vaults.w3.lido_contracts.accounting_oracle.get_last_processing_ref_slot = MagicMock(return_value=SlotNumber(6400))

        repot, block_number, block_hash = staking_vaults._get_start_point_for_fee_calculations(blockstamp, ipfs_data, frame_config, chain_config)

        assert repot.tree[0] == expected_report_root
        assert block_number == expected_block_number
        assert block_hash == expected_block_hash

    @pytest.mark.unit
    def test_get_start_point_invalid_tree_root_raises(self):
        staking_vaults = StakingVaultsService(w3=MagicMock())

        blockstamp = ReferenceBlockStamp(
            state_root=StateRoot(HexStr("0xabcabc")),
            slot_number=SlotNumber(1234),
            block_hash=BlockHash(HexStr("0xdeadbeef")),
            block_number=BlockNumber(4321),
            block_timestamp=Timestamp(1690000000),
            ref_slot=SlotNumber(1230),
            ref_epoch=EpochNumber(40),
        )

        ipfs_data = OnChainIpfsVaultReportData(
            timestamp=1690000100,
            tree_root=b'\xab\xcd\xef',
            report_cid="cid123"
        )

        frame_config = FrameConfig(
            initial_epoch=10,
            epochs_per_frame=2,
            fast_lane_length_slots=16
        )

        chain_config = ChainConfig(
            slots_per_epoch=32,
            seconds_per_slot=12,
            genesis_time=1600000000
        )

        fake_prev_report = StakingVaultIpfsReport(
            format=MagicMock(),
            leaf_encoding=MagicMock(),
            tree=["0xWRONGROOT"],
            values=MagicMock(),
            ref_slot=MagicMock(),
            block_number=MagicMock(),
            block_hash=MagicMock(),
            timestamp=MagicMock(),
            prev_tree_cid=MagicMock(),
            extra_values=MagicMock(),
        )

        staking_vaults.get_ipfs_report = MagicMock(return_value=fake_prev_report)
        staking_vaults.is_tree_root_valid = MagicMock(return_value=False)

        with pytest.raises(ValueError) as exc_info:
            staking_vaults._get_start_point_for_fee_calculations(blockstamp, ipfs_data, frame_config, chain_config)

        expected_hex = Web3.to_hex(ipfs_data.tree_root)
        assert f"Expected: {expected_hex}" in str(exc_info.value)

    @pytest.mark.unit
    def test_get_start_point_no_ipfs_but_has_oracle_data(self):
        web3 = MagicMock()

        expected_block_hash = BlockHash(HexStr("0x0abc1234def56789abc01234def0abcd12345678"))
        expected_block_number = BlockNumber(5_000)

        web3.cc.get_block_details.return_value = BlockDetailsResponse(
            message=BlockMessage(
                slot=MagicMock(),
                proposer_index=MagicMock(),
                parent_root=MagicMock(),
                state_root=MagicMock(),
                body=BeaconBlockBody(
                    execution_payload=ExecutionPayload(
                        parent_hash=MagicMock(),
                        block_number=expected_block_number,
                        timestamp=MagicMock(),
                        block_hash=expected_block_hash,
                    ),
                    attestations=MagicMock(),
                    sync_aggregate=SyncAggregate(
                        sync_committee_bits=MagicMock(),
                    ),
                ),
            ),
            signature=MagicMock(),
        )

        staking_vaults = StakingVaultsService(w3=web3)

        blockstamp = ReferenceBlockStamp(
            state_root=StateRoot(HexStr("0xabcabc")),
            slot_number=SlotNumber(1234),
            block_hash=BlockHash(HexStr("0xdeadbeef")),
            block_number=BlockNumber(4321),
            block_timestamp=Timestamp(1690000000),
            ref_slot=SlotNumber(1230),
            ref_epoch=EpochNumber(40),
        )

        ipfs_data = OnChainIpfsVaultReportData(
            timestamp=1690000100,
            tree_root=b'',
            report_cid=""  # NO DATA
        )

        frame_config = FrameConfig(
            initial_epoch=10,
            epochs_per_frame=2,
            fast_lane_length_slots=16
        )

        chain_config = ChainConfig(
            slots_per_epoch=32,
            seconds_per_slot=12,
            genesis_time=1600000000
        )

        slot_val = SlotNumber(6400)
        staking_vaults.w3.lido_contracts.accounting_oracle.get_last_processing_ref_slot = MagicMock(
            return_value=slot_val)

        prev_report, block_number, block_hash = staking_vaults._get_start_point_for_fee_calculations(
            blockstamp,
            ipfs_data,
            frame_config,
            chain_config,
        )

        assert prev_report is None
        assert block_number == expected_block_number
        assert block_hash == expected_block_hash

    @pytest.mark.unit
    def test_get_start_point_fresh_devnet_case(self):
        web3 = MagicMock()

        expected_block_hash = BlockHash(HexStr("0x0abc1234def56789abc01234def0abcd12345678"))
        expected_block_number = BlockNumber(6000)

        web3.cc.get_block_details.return_value = BlockDetailsResponse(
            message=BlockMessage(
                slot=MagicMock(),
                proposer_index=MagicMock(),
                parent_root=MagicMock(),
                state_root=MagicMock(),
                body=BeaconBlockBody(
                    execution_payload=ExecutionPayload(
                        parent_hash=MagicMock(),
                        block_number=expected_block_number,
                        timestamp=MagicMock(),
                        block_hash=expected_block_hash,
                    ),
                    attestations=MagicMock(),
                    sync_aggregate=SyncAggregate(sync_committee_bits=MagicMock()),
                ),
            ),
            signature=MagicMock(),
        )

        staking_vaults = StakingVaultsService(w3=web3)

        blockstamp = ReferenceBlockStamp(
            state_root=StateRoot(HexStr("0xabcabc")),
            slot_number=SlotNumber(1234),
            block_hash=BlockHash(HexStr("0xdeadbeef")),
            block_number=BlockNumber(4321),
            block_timestamp=Timestamp(1690000000),
            ref_slot=SlotNumber(1230),
            ref_epoch=EpochNumber(40),
        )

        ipfs_data = OnChainIpfsVaultReportData(
            timestamp=1690000100,
            tree_root=b'\xab\xcd\xef',
            report_cid=""  # важно!
        )

        frame_config = FrameConfig(
            initial_epoch=10,
            epochs_per_frame=2,
            fast_lane_length_slots=16
        )

        chain_config = ChainConfig(
            slots_per_epoch=32,
            seconds_per_slot=12,
            genesis_time=1600000000
        )

        # NO DATA from prev report
        staking_vaults.w3.lido_contracts.accounting_oracle.get_last_processing_ref_slot = MagicMock(return_value=None)

        prev_report, block_number, block_hash = staking_vaults._get_start_point_for_fee_calculations(
            blockstamp, ipfs_data, frame_config, chain_config
        )

        assert prev_report is None
        assert block_number == expected_block_number
        assert block_hash == expected_block_hash
