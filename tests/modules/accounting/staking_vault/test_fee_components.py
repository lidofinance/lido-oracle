from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from eth_typing import BlockNumber
from web3.types import Wei

from src.services.staking_vaults import StakingVaultsService
from src.utils.apr import get_steth_by_shares
from tests.modules.accounting.staking_vault.conftest import (
    FeeTestConstants,
    MintedSharesEventFactory,
    VaultAddresses,
    VaultInfoFactory,
)

# =============================================================================
# Tests
# =============================================================================


@pytest.mark.unit
class TestCalculateVaultFeeComponents:

    def test_no_events_uses_liability_shares(self):
        vault_info = VaultInfoFactory.build_with_fees(
            vault=VaultAddresses.VAULT_0,
            liability_shares=FeeTestConstants.LIABILITY_SHARES,
            mintable_st_eth=FeeTestConstants.MINTABLE_STETH,
            infra_fee_bp=FeeTestConstants.INFRA_FEE_BP,
            liquidity_fee_bp=FeeTestConstants.LIQUIDITY_FEE_BP,
            reservation_fee_bp=FeeTestConstants.RESERVATION_FEE_BP,
        )
        report_interval_seconds = 10
        core_apr_ratio = Decimal(1)
        pre_total_pooled_ether = 100
        pre_total_shares = 50
        minted_steth = get_steth_by_shares(vault_info.liability_shares, Wei(pre_total_pooled_ether), pre_total_shares)

        infra_fee, reservation_fee, liquidity_fee, liability_shares = (
            StakingVaultsService._calculate_vault_fee_components(
                vault_address=VaultAddresses.VAULT_0,
                vault_info=vault_info,
                vault_total_value=FeeTestConstants.VAULT_TOTAL_VALUE,
                vault_events=[],
                report_interval_seconds=report_interval_seconds,
                prev_ref_slot_timestamp=0,
                current_ref_slot_timestamp=10,
                core_apr_ratio=core_apr_ratio,
                pre_total_pooled_ether=pre_total_pooled_ether,
                pre_total_shares=pre_total_shares,
                block_timestamps={},
            )
        )

        assert infra_fee == StakingVaultsService.calc_fee_value(
            Decimal(FeeTestConstants.VAULT_TOTAL_VALUE),
            report_interval_seconds,
            core_apr_ratio,
            FeeTestConstants.INFRA_FEE_BP,
        )
        assert reservation_fee == StakingVaultsService.calc_fee_value(
            Decimal(FeeTestConstants.MINTABLE_STETH),
            report_interval_seconds,
            core_apr_ratio,
            FeeTestConstants.RESERVATION_FEE_BP,
        )
        assert liquidity_fee == StakingVaultsService.calc_fee_value(
            minted_steth,
            report_interval_seconds,
            core_apr_ratio,
            FeeTestConstants.LIQUIDITY_FEE_BP,
        )
        assert liability_shares == vault_info.liability_shares

    def test_with_events_uses_event_helper(self, monkeypatch):
        sentinel_fee = Decimal('123.45')
        sentinel_shares = 987
        helper_mock = MagicMock(return_value=(sentinel_fee, sentinel_shares))
        monkeypatch.setattr(StakingVaultsService, '_calculate_liquidity_fee_by_events', helper_mock)

        vault_info = VaultInfoFactory.build_with_fees(
            vault=VaultAddresses.VAULT_0,
            liability_shares=FeeTestConstants.LIABILITY_SHARES,
            mintable_st_eth=FeeTestConstants.MINTABLE_STETH,
            infra_fee_bp=FeeTestConstants.INFRA_FEE_BP,
            liquidity_fee_bp=FeeTestConstants.LIQUIDITY_FEE_BP,
            reservation_fee_bp=FeeTestConstants.RESERVATION_FEE_BP,
        )

        vault_events = [MintedSharesEventFactory.build(vault=VaultAddresses.VAULT_0)]
        block_timestamps = {BlockNumber(3600): 0}

        infra_fee, reservation_fee, liquidity_fee, liability_shares = (
            StakingVaultsService._calculate_vault_fee_components(
                vault_address=VaultAddresses.VAULT_0,
                vault_info=vault_info,
                vault_total_value=FeeTestConstants.VAULT_TOTAL_VALUE,
                vault_events=vault_events,
                report_interval_seconds=10,
                prev_ref_slot_timestamp=0,
                current_ref_slot_timestamp=10,
                core_apr_ratio=Decimal(1),
                pre_total_pooled_ether=100,
                pre_total_shares=50,
                block_timestamps=block_timestamps,
            )
        )

        helper_mock.assert_called_once()
        assert infra_fee == StakingVaultsService.calc_fee_value(
            Decimal(FeeTestConstants.VAULT_TOTAL_VALUE),
            10,
            Decimal(1),
            FeeTestConstants.INFRA_FEE_BP,
        )
        assert reservation_fee == StakingVaultsService.calc_fee_value(
            Decimal(FeeTestConstants.MINTABLE_STETH),
            10,
            Decimal(1),
            FeeTestConstants.RESERVATION_FEE_BP,
        )
        assert liquidity_fee == sentinel_fee
        assert liability_shares == sentinel_shares
