"""
Slashing reserve calculation tests.
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from eth_typing import ChecksumAddress, HexAddress, HexStr

from src.constants import TOTAL_BASIS_POINTS
from src.modules.accounting.types import VaultsMap
from src.modules.submodules.types import ChainConfig
from src.providers.consensus.types import Validator
from src.services.staking_vaults import StakingVaultsService
from src.types import EpochNumber, Gwei, ReferenceBlockStamp
from src.utils.units import gwei_to_wei
from tests.modules.accounting.staking_vault.conftest import (
    ValidatorFactory,
    ValidatorStateFactory,
    VaultInfoFactory,
)


class TestGetVaultsSlashingReserve:
    """Tests for get_vaults_slashing_reserve method."""

    @pytest.mark.unit
    def test_slashing_reserve_calculation(self):
        """Test slashing reserve calculation for slashed validators."""
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

        w3_mock = MagicMock()
        oracle_daemon_config_mock = MagicMock()
        oracle_daemon_config_mock.slashing_reserve_we_left_shift = MagicMock(return_value=8_192)
        oracle_daemon_config_mock.slashing_reserve_we_right_shift = MagicMock(return_value=8_192)

        cc_mock = MagicMock()
        cc_mock.get_validator_state = MagicMock(return_value=validator_1)

        w3_mock.lido_contracts.oracle_daemon_config = oracle_daemon_config_mock
        w3_mock.cc = cc_mock

        service = StakingVaultsService(w3_mock)
        result = service.get_vaults_slashing_reserve(ref_block_stamp, vaults_map, validators, chain_config)

        expected_reserve_1 = int(
            (Decimal(gwei_to_wei(validator_1.balance)) * Decimal(650) / Decimal(TOTAL_BASIS_POINTS)).to_integral_value()
        )
        expected_reserve_2 = int(
            (Decimal(gwei_to_wei(validator_2.balance)) * Decimal(650) / Decimal(TOTAL_BASIS_POINTS)).to_integral_value()
        )

        assert expected_reserve_1 == 2_080_000_000_000_000_000
        assert expected_reserve_2 == 4_160_000_000_000_000_000
        assert result == {vault_address_1: expected_reserve_1, vault_address_2: expected_reserve_2}
