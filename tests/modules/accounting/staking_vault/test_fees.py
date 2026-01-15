"""
Fee calculation tests for staking vaults.
"""

from collections import defaultdict
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from eth_typing import BlockNumber
from web3.types import Wei

from src.modules.oracles.accounting.events import VaultEventType
from src.services.staking_vaults import StakingVaultsService
from src.types import FrameNumber
from tests.modules.accounting.staking_vault.conftest import (
    BurnedSharesEventFactory,
    ExtraValueFactory,
    FeeTestConstants,
    MerkleValueFactory,
    MintedSharesEventFactory,
    OnChainIpfsVaultReportDataFactory,
    VaultAddresses,
    VaultConnectedEventFactory,
    VaultFeeFactory,
    VaultFeesUpdatedEventFactory,
    VaultInfoFactory,
)


class TestCalcFeeValue:
    """Tests for calc_fee_value static method."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        'vault_total_value, block_elapsed, core_apr_ratio, fee_bp, expected',
        [
            (
                FeeTestConstants.VAULT_TOTAL_VALUE,
                7_200,
                FeeTestConstants.CORE_APR_RATIO,
                FeeTestConstants.INFRA_FEE_BP,
                Decimal('2907180231545764.36775787768'),
            ),
            (
                FeeTestConstants.VAULT_TOTAL_VALUE,
                7_200 * 364,
                FeeTestConstants.CORE_APR_RATIO,
                FeeTestConstants.INFRA_FEE_BP,
                Decimal('1058213604282658229.86386748'),
            ),
        ],
    )
    def test_infra_fee_calculation(self, vault_total_value, block_elapsed, core_apr_ratio, fee_bp, expected):
        """Test infrastructure fee calculation."""
        result = StakingVaultsService.calc_fee_value(
            Decimal(vault_total_value), block_elapsed, Decimal(str(core_apr_ratio)), fee_bp
        )
        assert result == expected

    @pytest.mark.unit
    @pytest.mark.parametrize(
        'mintable_steth, block_elapsed, core_apr_ratio, fee_bp, expected',
        [
            (
                FeeTestConstants.MINTABLE_STETH,
                7_200,
                FeeTestConstants.CORE_APR_RATIO,
                FeeTestConstants.RESERVATION_FEE_BP,
                Decimal('7267950578864410.91939469422'),
            ),
            (
                FeeTestConstants.MINTABLE_STETH,
                7_200 * 364,
                FeeTestConstants.CORE_APR_RATIO,
                FeeTestConstants.RESERVATION_FEE_BP,
                Decimal('2645534010706645574.65966869'),
            ),
        ],
    )
    def test_reservation_fee_calculation(self, mintable_steth, block_elapsed, core_apr_ratio, fee_bp, expected):
        """Test reservation liquidity fee calculation."""
        result = StakingVaultsService.calc_fee_value(
            Decimal(mintable_steth), block_elapsed, Decimal(str(core_apr_ratio)), fee_bp
        )
        assert result == expected


class TestCalcLiquidityFee:
    """Tests for calc_liquidity_fee static method."""

    @pytest.mark.unit
    def test_no_events(self):
        """Test liquidity fee calculation with no events."""
        result = StakingVaultsService.calc_liquidity_fee(
            vault_address='0xVault1',
            liability_shares=FeeTestConstants.LIABILITY_SHARES,
            liquidity_fee_bp=FeeTestConstants.LIQUIDITY_FEE_BP,
            events={},
            prev_block_number=BlockNumber(0),
            current_block=BlockNumber(7_200),
            pre_total_pooled_ether=FeeTestConstants.PRE_TOTAL_POOLED_ETHER,
            pre_total_shares=FeeTestConstants.PRE_TOTAL_SHARES,
            core_apr_ratio=FeeTestConstants.CORE_APR_RATIO,
        )

        expected_fee = Decimal('20513697696884908.4459967120')
        expected_shares = 2_880_000_000_000_000_000_000

        assert result == (expected_fee, expected_shares)

    @pytest.mark.unit
    def test_with_events(self):
        """Test liquidity fee calculation with mint, burn, and fee update events."""
        vault_adr = '0xVault1'
        events = {
            vault_adr: [
                MintedSharesEventFactory.build(
                    vault=vault_adr,
                    block_number=BlockNumber(3_600),
                    amount_of_shares=8_998_437_744_1024,
                ),
                BurnedSharesEventFactory.build(
                    vault=vault_adr,
                    block_number=BlockNumber(3_700),
                    amount_of_shares=50_000_000,
                ),
                VaultFeesUpdatedEventFactory.build(
                    vault=vault_adr,
                    block_number=BlockNumber(3_200),
                    pre_liquidity_fee_bp=400,
                    liquidity_fee_bp=650,
                ),
            ]
        }

        result = StakingVaultsService.calc_liquidity_fee(
            vault_address=vault_adr,
            liability_shares=FeeTestConstants.LIABILITY_SHARES,
            liquidity_fee_bp=FeeTestConstants.LIQUIDITY_FEE_BP,
            events=events,
            prev_block_number=BlockNumber(0),
            current_block=BlockNumber(7_200),
            pre_total_pooled_ether=FeeTestConstants.PRE_TOTAL_POOLED_ETHER,
            pre_total_shares=FeeTestConstants.PRE_TOTAL_SHARES,
            core_apr_ratio=FeeTestConstants.CORE_APR_RATIO,
        )

        expected_fee = Decimal('17007082495056342.0072967912')
        expected_shares = 2_879_999_910_015_672_558_976

        assert result == (expected_fee, expected_shares)

    @pytest.mark.unit
    def test_raises_if_connected_with_non_zero_shares(self):
        """Test that calc_liquidity_fee raises when connected event has non-zero shares."""
        vault_address = '0xVault123'
        wrong_shares = 10_000_000

        minted_event = MintedSharesEventFactory.build(
            vault=vault_address,
            block_number=BlockNumber(105),
            amount_of_shares=1_000_000,
        )

        connected_event = VaultConnectedEventFactory.build(
            vault=vault_address,
            block_number=BlockNumber(101),
        )

        events: defaultdict[str, list[VaultEventType]] = defaultdict(list)
        events[vault_address] = [minted_event, connected_event]

        with pytest.raises(ValueError, match=r'Wrong vault liquidity shares by vault .* got .*'):
            StakingVaultsService.calc_liquidity_fee(
                vault_address=vault_address,
                liability_shares=wrong_shares,
                liquidity_fee_bp=100,
                events=events,
                prev_block_number=BlockNumber(100),
                current_block=BlockNumber(110),
                pre_total_pooled_ether=Wei(1_000_000_000_000_000_000_000),
                pre_total_shares=1_000_000_000_000_000_000_000,
                core_apr_ratio=Decimal('0.10'),
            )


class TestGetVaultsFees:
    """Tests for get_vaults_fees method."""

    @pytest.mark.unit
    def test_raises_if_liability_shares_mismatch(self, mock_vault_hub_events):
        """Test that get_vaults_fees raises when liability shares don't match."""
        vault_adr = VaultAddresses.VAULT_0

        mock_merkle_tree_data = OnChainIpfsVaultReportDataFactory.build()
        prev_report = MagicMock()
        prev_report.values = [
            MerkleValueFactory.build(
                vault_address=vault_adr,
                total_value_wei=Wei(0),
                fee=1_000,
                liability_shares=123_456_789,
                max_liability_shares=123_456_789,
            )
        ]
        prev_report.extra_values = {vault_adr: ExtraValueFactory.build(prev_fee='1000')}

        vault = VaultInfoFactory.build(
            vault=vault_adr,
            liability_shares=999_999_999,
            max_liability_shares=999_999_999,
        )

        vault_hub_mock = mock_vault_hub_events()

        w3_mock = MagicMock()
        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.lazy_oracle = MagicMock()

        service = StakingVaultsService(w3_mock)
        service._get_start_point_for_fee_calculations = MagicMock(return_value=[prev_report, 0])

        mock_ref_block = MagicMock()
        mock_ref_block.block_number = 7_200

        with pytest.raises(ValueError, match='Wrong liability shares by vault'):
            service.get_vaults_fees(
                blockstamp=mock_ref_block,
                vaults={vault_adr: vault},
                vaults_total_values={vault_adr: 0},
                latest_onchain_ipfs_report_data=mock_merkle_tree_data,
                core_apr_ratio=Decimal('0.3'),
                pre_total_pooled_ether=1,
                pre_total_shares=1,
                frame_config=MagicMock(),
                chain_config=MagicMock(),
                current_frame=FrameNumber(0),
            )

    @pytest.mark.unit
    def test_prev_fee_reset_after_reconnect(self, mock_vault_hub_events):
        """Ensure prev_fee is reset to zero when a vault reconnects."""
        vault_adr = VaultAddresses.VAULT_0

        prev_report = MagicMock()
        prev_report.values = [
            MerkleValueFactory.build(
                vault_address=vault_adr,
                fee=12_345,
                liability_shares=0,
                max_liability_shares=0,
            )
        ]
        prev_report.extra_values = {vault_adr: ExtraValueFactory.build(prev_fee='12345')}

        vault = VaultInfoFactory.build_with_fees(
            vault=vault_adr,
            liability_shares=0,
            max_liability_shares=0,
            mintable_st_eth=FeeTestConstants.MINTABLE_STETH,
        )

        connected_events = [VaultConnectedEventFactory.build(vault=vault_adr, block_number=BlockNumber(10))]
        vault_hub_mock = mock_vault_hub_events(connected_events=connected_events)

        w3_mock = MagicMock()
        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.lazy_oracle = MagicMock()

        service = StakingVaultsService(w3_mock)
        service._get_start_point_for_fee_calculations = MagicMock(return_value=[prev_report, 0])

        blockstamp = MagicMock()
        blockstamp.block_number = 100

        fees = service.get_vaults_fees(
            blockstamp=blockstamp,
            vaults={vault_adr: vault},
            vaults_total_values={vault_adr: FeeTestConstants.VAULT_TOTAL_VALUE},
            latest_onchain_ipfs_report_data=OnChainIpfsVaultReportDataFactory.build(),
            core_apr_ratio=FeeTestConstants.CORE_APR_RATIO,
            pre_total_pooled_ether=FeeTestConstants.PRE_TOTAL_POOLED_ETHER,
            pre_total_shares=FeeTestConstants.PRE_TOTAL_SHARES,
            frame_config=MagicMock(),
            chain_config=MagicMock(),
            current_frame=FrameNumber(0),
        )

        assert fees[vault_adr].prev_fee == 0
