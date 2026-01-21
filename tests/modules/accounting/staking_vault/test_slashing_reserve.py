from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from eth_typing import ChecksumAddress, HexAddress, HexStr

from src.constants import TOTAL_BASIS_POINTS
from src.modules.accounting.types import VaultsMap
from src.modules.submodules.types import ChainConfig
from src.providers.consensus.types import Validator
from src.services.staking_vaults import StakingVaultsService
from src.types import EpochNumber, Gwei, ReferenceBlockStamp, SlotNumber
from src.utils.units import gwei_to_wei
from tests.modules.accounting.staking_vault.conftest import (
    ValidatorFactory,
    ValidatorStateFactory,
    VaultInfoFactory,
)

# =============================================================================
# Tests
# =============================================================================


@pytest.mark.unit
class TestGetVaultsSlashingReserve:

    def test_slashing_reserve_calculation(self, web3):
        # Setup
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

        vault_address_1 = ChecksumAddress(HexAddress(HexStr('0x1234567890abcdef1234567890abcdef12345678')))
        vault_address_2 = ChecksumAddress(HexAddress(HexStr('0x2222222222222222222222222222222222222222')))

        wc_1 = 'withdrawal_credentials_1'
        wc_2 = 'withdrawal_credentials_2'

        vaults_map: VaultsMap = {
            vault_address_1: VaultInfoFactory.build(
                vault=vault_address_1,
                withdrawal_credentials=wc_1,
                reserve_ratio_bp=650,
            ),
            vault_address_2: VaultInfoFactory.build(
                vault=vault_address_2,
                withdrawal_credentials=wc_2,
                reserve_ratio_bp=650,
            ),
        }

        validator_1 = ValidatorFactory.build(
            balance=Gwei(32_000_000_000),
            validator=ValidatorStateFactory.build(
                withdrawal_credentials=wc_1,
                slashed=True,
                withdrawable_epoch=mock_ref_epoch,
            ),
        )

        validator_2 = ValidatorFactory.build(
            balance=Gwei(64_000_000_000),
            validator=ValidatorStateFactory.build(
                withdrawal_credentials=wc_2,
                slashed=True,
                withdrawable_epoch=EpochNumber(50_000),
            ),
        )

        validator_3 = ValidatorFactory.build(
            balance=Gwei(64_000_000_000),
            validator=ValidatorStateFactory.build(
                withdrawal_credentials=wc_1,
                slashed=False,
            ),
        )

        validators: list[Validator] = [validator_1, validator_2, validator_3]

        chain_config = ChainConfig(
            slots_per_epoch=32,
            seconds_per_slot=MagicMock(),
            genesis_time=MagicMock(),
        )

        oracle_daemon_config_mock = MagicMock()
        oracle_daemon_config_mock.slashing_reserve_we_left_shift = MagicMock(return_value=8_192)
        oracle_daemon_config_mock.slashing_reserve_we_right_shift = MagicMock(return_value=8_192)

        cc_mock = MagicMock()
        cc_mock.get_validator_state = MagicMock(return_value=validator_1)

        web3.lido_contracts.oracle_daemon_config = oracle_daemon_config_mock
        web3.cc = cc_mock

        service = StakingVaultsService(web3)

        # Act
        result = service.get_vaults_slashing_reserve(ref_block_stamp, vaults_map, validators, chain_config)

        # Assert
        expected_reserve_1 = int(
            (Decimal(gwei_to_wei(validator_1.balance)) * Decimal(650) / Decimal(TOTAL_BASIS_POINTS)).to_integral_value()
        )
        expected_reserve_2 = int(
            (Decimal(gwei_to_wei(validator_2.balance)) * Decimal(650) / Decimal(TOTAL_BASIS_POINTS)).to_integral_value()
        )

        assert expected_reserve_1 == 2_080_000_000_000_000_000
        assert expected_reserve_2 == 4_160_000_000_000_000_000
        assert result == {vault_address_1: expected_reserve_1, vault_address_2: expected_reserve_2}

    def test_slashing_reserve_boundary_uses_past_state(self, web3):
        # Setup
        mock_ref_epoch = EpochNumber(10_000)
        left_shift = 100
        right_shift = 200

        ref_block_stamp = ReferenceBlockStamp(
            state_root=MagicMock(),
            slot_number=MagicMock(),
            block_hash=MagicMock(),
            block_number=MagicMock(),
            block_timestamp=MagicMock(),
            ref_slot=MagicMock(),
            ref_epoch=EpochNumber(mock_ref_epoch - left_shift),
        )

        vault_address = ChecksumAddress(HexAddress(HexStr('0x1234567890abcdef1234567890abcdef12345678')))
        wc = 'withdrawal_credentials_1'

        vaults_map: VaultsMap = {
            vault_address: VaultInfoFactory.build(
                vault=vault_address,
                withdrawal_credentials=wc,
                reserve_ratio_bp=650,
            ),
        }

        validator_1 = ValidatorFactory.build(
            balance=Gwei(32_000_000_000),
            validator=ValidatorStateFactory.build(
                withdrawal_credentials=wc,
                slashed=True,
                withdrawable_epoch=mock_ref_epoch,
            ),
        )
        validator_2 = ValidatorFactory.build(
            balance=Gwei(16_000_000_000),
            validator=ValidatorStateFactory.build(
                withdrawal_credentials=wc,
                slashed=True,
                withdrawable_epoch=mock_ref_epoch,
            ),
        )

        validators: list[Validator] = [validator_1, validator_2]

        chain_config = ChainConfig(
            slots_per_epoch=32,
            seconds_per_slot=MagicMock(),
            genesis_time=MagicMock(),
        )

        oracle_daemon_config_mock = MagicMock()
        oracle_daemon_config_mock.slashing_reserve_we_left_shift = MagicMock(return_value=left_shift)
        oracle_daemon_config_mock.slashing_reserve_we_right_shift = MagicMock(return_value=right_shift)

        past_state_1 = ValidatorFactory.build(balance=Gwei(8_000_000_000))
        past_state_2 = ValidatorFactory.build(balance=Gwei(4_000_000_000))

        cc_mock = MagicMock()
        cc_mock.get_validator_state.side_effect = [past_state_1, past_state_2]

        web3.lido_contracts.oracle_daemon_config = oracle_daemon_config_mock
        web3.cc = cc_mock

        service = StakingVaultsService(web3)

        # Act
        result = service.get_vaults_slashing_reserve(ref_block_stamp, vaults_map, validators, chain_config)

        # Assert
        expected_slot_id = (mock_ref_epoch - left_shift) * chain_config.slots_per_epoch
        cc_mock.get_validator_state.assert_any_call(SlotNumber(expected_slot_id), validator_1.index)
        cc_mock.get_validator_state.assert_any_call(SlotNumber(expected_slot_id), validator_2.index)

        expected_reserve = int(
            (
                Decimal(gwei_to_wei(past_state_1.balance)) * Decimal(650) / Decimal(TOTAL_BASIS_POINTS)
            ).to_integral_value()
        ) + int(
            (
                Decimal(gwei_to_wei(past_state_2.balance)) * Decimal(650) / Decimal(TOTAL_BASIS_POINTS)
            ).to_integral_value()
        )
        assert result == {vault_address: expected_reserve}

    def test_slashing_reserve_before_window_uses_current_balance(self, web3):
        # Setup
        mock_ref_epoch = EpochNumber(10_000)
        left_shift = 100

        ref_block_stamp = ReferenceBlockStamp(
            state_root=MagicMock(),
            slot_number=MagicMock(),
            block_hash=MagicMock(),
            block_number=MagicMock(),
            block_timestamp=MagicMock(),
            ref_slot=MagicMock(),
            ref_epoch=EpochNumber(mock_ref_epoch - left_shift - 1),
        )

        vault_address = ChecksumAddress(HexAddress(HexStr('0x2222222222222222222222222222222222222222')))
        wc = 'withdrawal_credentials_2'

        vaults_map: VaultsMap = {
            vault_address: VaultInfoFactory.build(
                vault=vault_address,
                withdrawal_credentials=wc,
                reserve_ratio_bp=650,
            ),
        }

        validator_1 = ValidatorFactory.build(
            balance=Gwei(12_000_000_000),
            validator=ValidatorStateFactory.build(
                withdrawal_credentials=wc,
                slashed=True,
                withdrawable_epoch=mock_ref_epoch,
            ),
        )
        validator_2 = ValidatorFactory.build(
            balance=Gwei(8_000_000_000),
            validator=ValidatorStateFactory.build(
                withdrawal_credentials=wc,
                slashed=True,
                withdrawable_epoch=mock_ref_epoch,
            ),
        )

        chain_config = ChainConfig(
            slots_per_epoch=32,
            seconds_per_slot=MagicMock(),
            genesis_time=MagicMock(),
        )

        oracle_daemon_config_mock = MagicMock()
        oracle_daemon_config_mock.slashing_reserve_we_left_shift = MagicMock(return_value=left_shift)
        oracle_daemon_config_mock.slashing_reserve_we_right_shift = MagicMock(return_value=200)

        cc_mock = MagicMock()

        web3.lido_contracts.oracle_daemon_config = oracle_daemon_config_mock
        web3.cc = cc_mock

        service = StakingVaultsService(web3)

        # Act
        result = service.get_vaults_slashing_reserve(
            ref_block_stamp, vaults_map, [validator_1, validator_2], chain_config
        )

        # Assert
        cc_mock.get_validator_state.assert_not_called()
        expected_reserve = int(
            (Decimal(gwei_to_wei(validator_1.balance)) * Decimal(650) / Decimal(TOTAL_BASIS_POINTS)).to_integral_value()
        ) + int(
            (Decimal(gwei_to_wei(validator_2.balance)) * Decimal(650) / Decimal(TOTAL_BASIS_POINTS)).to_integral_value()
        )
        assert result == {vault_address: expected_reserve}

    def test_slashing_reserve_upper_boundary_uses_past_state(self, web3):
        # Setup
        mock_ref_epoch = EpochNumber(10_000)
        left_shift = 100
        right_shift = 200

        ref_block_stamp = ReferenceBlockStamp(
            state_root=MagicMock(),
            slot_number=MagicMock(),
            block_hash=MagicMock(),
            block_number=MagicMock(),
            block_timestamp=MagicMock(),
            ref_slot=MagicMock(),
            ref_epoch=EpochNumber(mock_ref_epoch + right_shift),
        )

        vault_address = ChecksumAddress(HexAddress(HexStr('0x3333333333333333333333333333333333333333')))
        wc = 'withdrawal_credentials_3'

        vaults_map: VaultsMap = {
            vault_address: VaultInfoFactory.build(
                vault=vault_address,
                withdrawal_credentials=wc,
                reserve_ratio_bp=650,
            ),
        }

        validator = ValidatorFactory.build(
            balance=Gwei(20_000_000_000),
            validator=ValidatorStateFactory.build(
                withdrawal_credentials=wc,
                slashed=True,
                withdrawable_epoch=mock_ref_epoch,
            ),
        )

        chain_config = ChainConfig(
            slots_per_epoch=32,
            seconds_per_slot=MagicMock(),
            genesis_time=MagicMock(),
        )

        oracle_daemon_config_mock = MagicMock()
        oracle_daemon_config_mock.slashing_reserve_we_left_shift = MagicMock(return_value=left_shift)
        oracle_daemon_config_mock.slashing_reserve_we_right_shift = MagicMock(return_value=right_shift)

        past_state = ValidatorFactory.build(balance=Gwei(6_000_000_000))

        cc_mock = MagicMock()
        cc_mock.get_validator_state.return_value = past_state

        web3.lido_contracts.oracle_daemon_config = oracle_daemon_config_mock
        web3.cc = cc_mock

        service = StakingVaultsService(web3)

        # Act
        result = service.get_vaults_slashing_reserve(ref_block_stamp, vaults_map, [validator], chain_config)

        # Assert
        expected_slot_id = (mock_ref_epoch - left_shift) * chain_config.slots_per_epoch
        cc_mock.get_validator_state.assert_called_once_with(SlotNumber(expected_slot_id), validator.index)

        expected_reserve = int(
            (Decimal(gwei_to_wei(past_state.balance)) * Decimal(650) / Decimal(TOTAL_BASIS_POINTS)).to_integral_value()
        )
        assert result == {vault_address: expected_reserve}

    def test_slashing_reserve_after_window_no_reserve(self, web3):
        # Setup
        mock_ref_epoch = EpochNumber(10_000)
        left_shift = 200
        right_shift = 100

        ref_block_stamp = ReferenceBlockStamp(
            state_root=MagicMock(),
            slot_number=MagicMock(),
            block_hash=MagicMock(),
            block_number=MagicMock(),
            block_timestamp=MagicMock(),
            ref_slot=MagicMock(),
            ref_epoch=EpochNumber(mock_ref_epoch + right_shift + 1),
        )

        vault_address = ChecksumAddress(HexAddress(HexStr('0x4444444444444444444444444444444444444444')))
        wc = 'withdrawal_credentials_4'

        vaults_map: VaultsMap = {
            vault_address: VaultInfoFactory.build(
                vault=vault_address,
                withdrawal_credentials=wc,
                reserve_ratio_bp=650,
            ),
        }

        validator = ValidatorFactory.build(
            balance=Gwei(32_000_000_000),
            validator=ValidatorStateFactory.build(
                withdrawal_credentials=wc,
                slashed=True,
                withdrawable_epoch=mock_ref_epoch,
            ),
        )

        chain_config = ChainConfig(
            slots_per_epoch=32,
            seconds_per_slot=MagicMock(),
            genesis_time=MagicMock(),
        )

        oracle_daemon_config_mock = MagicMock()
        oracle_daemon_config_mock.slashing_reserve_we_left_shift = MagicMock(return_value=left_shift)
        oracle_daemon_config_mock.slashing_reserve_we_right_shift = MagicMock(return_value=right_shift)

        cc_mock = MagicMock()

        web3.lido_contracts.oracle_daemon_config = oracle_daemon_config_mock
        web3.cc = cc_mock

        service = StakingVaultsService(web3)

        # Act
        result = service.get_vaults_slashing_reserve(ref_block_stamp, vaults_map, [validator], chain_config)

        # Assert
        cc_mock.get_validator_state.assert_not_called()
        assert result == {}
