"""
Fee calculation tests for staking vaults.
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from eth_typing import BlockNumber
from web3.types import Wei

from src.constants import SECONDS_IN_YEAR, TOTAL_BASIS_POINTS
from src.services.staking_vaults import StakingVaultsService
from src.types import FrameNumber, SlotNumber
from src.utils.apr import get_steth_by_shares
from tests.modules.accounting.staking_vault.conftest import (
    BadDebtSocializedEventFactory,
    BadDebtWrittenOffEventFactory,
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
    VaultRebalancedEventFactory,
)


class TestCalcFeeValue:
    """Tests for calc_fee_value static method."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        'vault_total_value, time_elapsed_seconds, core_apr_ratio, fee_bp, expected',
        [
            (
                FeeTestConstants.VAULT_TOTAL_VALUE,
                7_200 * FeeTestConstants.SECONDS_PER_SLOT,
                FeeTestConstants.CORE_APR_RATIO,
                FeeTestConstants.INFRA_FEE_BP,
                Decimal('2907180231545764.36775787768'),
            ),
            (
                FeeTestConstants.VAULT_TOTAL_VALUE,
                7_200 * 364 * FeeTestConstants.SECONDS_PER_SLOT,
                FeeTestConstants.CORE_APR_RATIO,
                FeeTestConstants.INFRA_FEE_BP,
                Decimal('1058213604282658229.86386748'),
            ),
        ],
    )
    def test_infra_fee_calculation(self, vault_total_value, time_elapsed_seconds, core_apr_ratio, fee_bp, expected):
        """Test infrastructure fee calculation."""
        result = StakingVaultsService.calc_fee_value(
            Decimal(vault_total_value), time_elapsed_seconds, Decimal(str(core_apr_ratio)), fee_bp
        )
        assert result == expected

    @pytest.mark.unit
    @pytest.mark.parametrize(
        'mintable_steth, time_elapsed_seconds, core_apr_ratio, fee_bp, expected',
        [
            (
                FeeTestConstants.MINTABLE_STETH,
                7_200 * FeeTestConstants.SECONDS_PER_SLOT,
                FeeTestConstants.CORE_APR_RATIO,
                FeeTestConstants.RESERVATION_FEE_BP,
                Decimal('7267950578864410.91939469419'),
            ),
            (
                FeeTestConstants.MINTABLE_STETH,
                7_200 * 364 * FeeTestConstants.SECONDS_PER_SLOT,
                FeeTestConstants.CORE_APR_RATIO,
                FeeTestConstants.RESERVATION_FEE_BP,
                Decimal('2645534010706645574.65966869'),
            ),
        ],
    )
    def test_reservation_fee_calculation(self, mintable_steth, time_elapsed_seconds, core_apr_ratio, fee_bp, expected):
        """Test reservation liquidity fee calculation."""
        result = StakingVaultsService.calc_fee_value(
            Decimal(mintable_steth), time_elapsed_seconds, Decimal(str(core_apr_ratio)), fee_bp
        )
        assert result == expected

    @pytest.mark.unit
    @pytest.mark.parametrize(
        'minted_steth, time_elapsed_seconds, core_apr_ratio, fee_bp, expected',
        [
            (
                FeeTestConstants.MINTABLE_STETH,
                7_200 * FeeTestConstants.SECONDS_PER_SLOT,
                FeeTestConstants.CORE_APR_RATIO,
                FeeTestConstants.LIQUIDITY_FEE_BP,
                Decimal('18896671505047468.3904262049'),
            ),
            (
                FeeTestConstants.MINTABLE_STETH,
                7_200 * 364 * FeeTestConstants.SECONDS_PER_SLOT,
                FeeTestConstants.CORE_APR_RATIO,
                FeeTestConstants.LIQUIDITY_FEE_BP,
                Decimal('6878388427837278494.11513860'),
            ),
        ],
    )
    def test_liquidity_fee_calculation(self, minted_steth, time_elapsed_seconds, core_apr_ratio, fee_bp, expected):
        """Test liquidity fee calculation."""
        result = StakingVaultsService.calc_fee_value(
            Decimal(minted_steth), time_elapsed_seconds, Decimal(str(core_apr_ratio)), fee_bp
        )
        assert result == expected


class TestBuildPrevReportMaps:
    """Tests for _build_prev_report_maps helper."""

    @pytest.mark.unit
    def test_no_prev_report(self):
        """Empty maps should default to zero for missing entries."""
        prev_fee_map, prev_liability_shares_map = StakingVaultsService._build_prev_report_maps(None)

        assert prev_fee_map[VaultAddresses.VAULT_0] == 0
        assert prev_liability_shares_map[VaultAddresses.VAULT_0] == 0

    @pytest.mark.unit
    def test_empty_prev_report_values(self):
        """Empty report values should still return zero-default maps."""
        prev_report = MagicMock()
        prev_report.values = []

        prev_fee_map, prev_liability_shares_map = StakingVaultsService._build_prev_report_maps(prev_report)

        assert prev_fee_map[VaultAddresses.VAULT_1] == 0
        assert prev_liability_shares_map[VaultAddresses.VAULT_1] == 0

    @pytest.mark.unit
    def test_with_prev_report(self):
        """Maps should reflect previous report fees and liability shares."""
        vault_0 = MerkleValueFactory.build(vault_address=VaultAddresses.VAULT_0, fee=111, liability_shares=222)
        vault_1 = MerkleValueFactory.build(vault_address=VaultAddresses.VAULT_1, fee=333, liability_shares=444)
        prev_report = MagicMock()
        prev_report.values = [vault_0, vault_1]

        prev_fee_map, prev_liability_shares_map = StakingVaultsService._build_prev_report_maps(prev_report)

        assert prev_fee_map[VaultAddresses.VAULT_0] == 111
        assert prev_fee_map[VaultAddresses.VAULT_1] == 333
        assert prev_liability_shares_map[VaultAddresses.VAULT_0] == 222
        assert prev_liability_shares_map[VaultAddresses.VAULT_1] == 444
        assert set(prev_fee_map.keys()) == {VaultAddresses.VAULT_0, VaultAddresses.VAULT_1}
        assert set(prev_liability_shares_map.keys()) == {VaultAddresses.VAULT_0, VaultAddresses.VAULT_1}


class TestCalculateLiquidityFeeByEvents:
    """Tests for _calculate_liquidity_fee_by_events static method."""

    @pytest.mark.unit
    def test_with_events(self):
        """Test liquidity fee calculation with mint, burn, and fee update events."""
        vault_adr = VaultAddresses.VAULT_0
        vault_events = [
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

        result = StakingVaultsService._calculate_liquidity_fee_by_events(
            vault_address=vault_adr,
            liability_shares=FeeTestConstants.LIABILITY_SHARES,
            liquidity_fee_bp=FeeTestConstants.LIQUIDITY_FEE_BP,
            vault_events=vault_events,
            prev_report_timestamp=0,
            current_report_timestamp=7_200 * FeeTestConstants.SECONDS_PER_SLOT,
            pre_total_pooled_ether=FeeTestConstants.PRE_TOTAL_POOLED_ETHER,
            pre_total_shares=FeeTestConstants.PRE_TOTAL_SHARES,
            core_apr_ratio=FeeTestConstants.CORE_APR_RATIO,
            block_timestamps={
                BlockNumber(3_600): 3_600 * FeeTestConstants.SECONDS_PER_SLOT,
                BlockNumber(3_700): 3_700 * FeeTestConstants.SECONDS_PER_SLOT,
                BlockNumber(3_200): 3_200 * FeeTestConstants.SECONDS_PER_SLOT,
            },
            seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT,
        )

        expected_fee = Decimal('17007082495056342.0567607613')
        expected_shares = 2_879_999_910_015_672_558_976

        assert result == (expected_fee, expected_shares)

    @pytest.mark.unit
    def test_fee_update_ordered_by_log_index(self):
        """Fee updates in the same block should be applied in log index order."""
        vault_adr = VaultAddresses.VAULT_0
        event_low = VaultFeesUpdatedEventFactory.build(
            vault=vault_adr,
            block_number=BlockNumber(1),
            log_index=1,
            pre_liquidity_fee_bp=100,
        )
        event_high = VaultFeesUpdatedEventFactory.build(
            vault=vault_adr,
            block_number=BlockNumber(1),
            log_index=2,
            pre_liquidity_fee_bp=200,
        )

        fee, shares = StakingVaultsService._calculate_liquidity_fee_by_events(
            vault_address=vault_adr,
            liability_shares=10,
            liquidity_fee_bp=650,
            vault_events=[event_low, event_high],
            prev_report_timestamp=0,
            current_report_timestamp=20,
            pre_total_pooled_ether=Wei(1),
            pre_total_shares=1,
            core_apr_ratio=Decimal(1),
            block_timestamps={BlockNumber(1): 10},
            seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT,
        )

        expected_fee = StakingVaultsService.calc_fee_value(Decimal(10), 10, Decimal(1), 650) + (
            StakingVaultsService.calc_fee_value(Decimal(10), 10, Decimal(1), 100)
        )
        assert fee == expected_fee
        assert shares == 10

    @pytest.mark.unit
    def test_raises_if_connected_with_non_zero_shares(self):
        """Test that event-based liquidity fee raises when connected event has non-zero shares."""
        vault_address = VaultAddresses.VAULT_2
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

        vault_events = [minted_event, connected_event]

        with pytest.raises(ValueError, match=r'Wrong vault liquidity shares by vault .* got .*'):
            StakingVaultsService._calculate_liquidity_fee_by_events(
                vault_address=vault_address,
                liability_shares=wrong_shares,
                liquidity_fee_bp=100,
                vault_events=vault_events,
                prev_report_timestamp=100 * FeeTestConstants.SECONDS_PER_SLOT,
                current_report_timestamp=110 * FeeTestConstants.SECONDS_PER_SLOT,
                pre_total_pooled_ether=Wei(1_000_000_000_000_000_000_000),
                pre_total_shares=1_000_000_000_000_000_000_000,
                core_apr_ratio=Decimal('0.10'),
                block_timestamps={
                    BlockNumber(101): 101 * FeeTestConstants.SECONDS_PER_SLOT,
                    BlockNumber(105): 105 * FeeTestConstants.SECONDS_PER_SLOT,
                },
                seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT,
            )

    @pytest.mark.unit
    def test_flashloan_same_block_mint_and_burn_counts_full_slot(self):
        """Mint at block start and burn at block end should accrue a full-slot fee."""
        vault_adr = VaultAddresses.VAULT_0
        minted_event = MintedSharesEventFactory.build(
            vault=vault_adr,
            block_number=BlockNumber(1),
            amount_of_shares=1,
        )
        burned_event = BurnedSharesEventFactory.build(
            vault=vault_adr,
            block_number=BlockNumber(1),
            amount_of_shares=1,
        )
        vault_events = [minted_event, burned_event]
        block_timestamps = {BlockNumber(1): 0}
        mint_timestamp = StakingVaultsService._get_event_effective_timestamp(
            minted_event, vault_adr, block_timestamps, FeeTestConstants.SECONDS_PER_SLOT
        )
        burn_timestamp = StakingVaultsService._get_event_effective_timestamp(
            burned_event, vault_adr, block_timestamps, FeeTestConstants.SECONDS_PER_SLOT
        )

        fee, shares = StakingVaultsService._calculate_liquidity_fee_by_events(
            vault_address=vault_adr,
            liability_shares=0,
            liquidity_fee_bp=TOTAL_BASIS_POINTS,
            vault_events=vault_events,
            prev_report_timestamp=0,
            current_report_timestamp=FeeTestConstants.SECONDS_PER_SLOT,
            pre_total_pooled_ether=Wei(1),
            pre_total_shares=1,
            core_apr_ratio=Decimal(1),
            block_timestamps=block_timestamps,
            seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT,
        )

        assert mint_timestamp == 0
        assert burn_timestamp == FeeTestConstants.SECONDS_PER_SLOT
        assert burn_timestamp > mint_timestamp

        expected_fee = StakingVaultsService.calc_fee_value(
            Decimal(1), FeeTestConstants.SECONDS_PER_SLOT, Decimal(1), TOTAL_BASIS_POINTS
        )
        assert fee == expected_fee
        assert shares == 0

    @pytest.mark.unit
    def test_raises_if_event_timestamp_missing(self):
        """Missing execution timestamp mapping should fail fast."""
        vault_adr = VaultAddresses.VAULT_0
        vault_events = [
            MintedSharesEventFactory.build(
                vault=vault_adr,
                block_number=BlockNumber(1),
                amount_of_shares=1,
            ),
        ]

        with pytest.raises(ValueError, match='Missing timestamp for block 1'):
            StakingVaultsService._calculate_liquidity_fee_by_events(
                vault_address=vault_adr,
                liability_shares=1,
                liquidity_fee_bp=TOTAL_BASIS_POINTS,
                vault_events=vault_events,
                prev_report_timestamp=0,
                current_report_timestamp=FeeTestConstants.SECONDS_PER_SLOT,
                pre_total_pooled_ether=Wei(1),
                pre_total_shares=1,
                core_apr_ratio=Decimal(1),
                block_timestamps={},
                seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT,
            )

    @pytest.mark.unit
    def test_raises_if_event_after_current_report(self):
        """Event timestamps after the report should be rejected."""
        vault_adr = VaultAddresses.VAULT_0
        vault_events = [
            MintedSharesEventFactory.build(
                vault=vault_adr,
                block_number=BlockNumber(1),
                amount_of_shares=1,
            ),
        ]

        with pytest.raises(ValueError, match='Negative time/slot interval'):
            StakingVaultsService._calculate_liquidity_fee_by_events(
                vault_address=vault_adr,
                liability_shares=1,
                liquidity_fee_bp=TOTAL_BASIS_POINTS,
                vault_events=vault_events,
                prev_report_timestamp=0,
                current_report_timestamp=1,
                pre_total_pooled_ether=Wei(1),
                pre_total_shares=1,
                core_apr_ratio=Decimal(1),
                block_timestamps={BlockNumber(1): 10},
                seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT,
            )

    @pytest.mark.unit
    def test_bad_debt_socialized_time_shift_for_donor_and_acceptor(self):
        """Bad debt donor uses end-of-slot timing, acceptor uses start-of-slot timing."""
        vault_donor = VaultAddresses.VAULT_0
        vault_acceptor = VaultAddresses.VAULT_1
        event = BadDebtSocializedEventFactory.build(
            vault_donor=vault_donor,
            vault_acceptor=vault_acceptor,
            block_number=BlockNumber(1),
            bad_debt_shares=4,
        )

        block_timestamps = {BlockNumber(1): 0}
        donor_timestamp = StakingVaultsService._get_event_effective_timestamp(
            event, vault_donor, block_timestamps, FeeTestConstants.SECONDS_PER_SLOT
        )
        acceptor_timestamp = StakingVaultsService._get_event_effective_timestamp(
            event, vault_acceptor, block_timestamps, FeeTestConstants.SECONDS_PER_SLOT
        )
        assert donor_timestamp == FeeTestConstants.SECONDS_PER_SLOT
        assert acceptor_timestamp == 0
        assert donor_timestamp > acceptor_timestamp

        # Donor path (decrease): event effective time is end-of-slot, so we accrue one slot on 10 shares,
        # then add back 4 shares and accrue another slot on 14 shares.
        expected_donor_fee = StakingVaultsService.calc_fee_value(
            Decimal(10), FeeTestConstants.SECONDS_PER_SLOT, Decimal(1), TOTAL_BASIS_POINTS
        ) + StakingVaultsService.calc_fee_value(
            Decimal(14), FeeTestConstants.SECONDS_PER_SLOT, Decimal(1), TOTAL_BASIS_POINTS
        )
        # Acceptor path (increase): event effective time is start-of-slot, so we accrue two slots on 10 shares.
        expected_acceptor_fee = StakingVaultsService.calc_fee_value(
            Decimal(10), 2 * FeeTestConstants.SECONDS_PER_SLOT, Decimal(1), TOTAL_BASIS_POINTS
        )

        donor_fee, _ = StakingVaultsService._calculate_liquidity_fee_by_events(
            vault_address=vault_donor,
            liability_shares=10,
            liquidity_fee_bp=TOTAL_BASIS_POINTS,
            vault_events=[event],
            prev_report_timestamp=0,
            current_report_timestamp=2 * FeeTestConstants.SECONDS_PER_SLOT,
            pre_total_pooled_ether=Wei(1),
            pre_total_shares=1,
            core_apr_ratio=Decimal(1),
            block_timestamps=block_timestamps,
            seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT,
        )

        acceptor_fee, _ = StakingVaultsService._calculate_liquidity_fee_by_events(
            vault_address=vault_acceptor,
            liability_shares=10,
            liquidity_fee_bp=TOTAL_BASIS_POINTS,
            vault_events=[event],
            prev_report_timestamp=0,
            current_report_timestamp=2 * FeeTestConstants.SECONDS_PER_SLOT,
            pre_total_pooled_ether=Wei(1),
            pre_total_shares=1,
            core_apr_ratio=Decimal(1),
            block_timestamps=block_timestamps,
            seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT,
        )

        assert donor_fee == expected_donor_fee
        assert acceptor_fee == expected_acceptor_fee


class TestGetEventEffectiveTimestamp:
    """Tests for _get_event_effective_timestamp helper."""

    @pytest.mark.unit
    def test_increase_events_use_slot_start(self):
        """Mint/fee-update/acceptor events should be effective at slot start."""
        block_timestamps = {BlockNumber(1): 100}
        seconds_per_slot = FeeTestConstants.SECONDS_PER_SLOT

        minted_event = MintedSharesEventFactory.build(vault=VaultAddresses.VAULT_0, block_number=BlockNumber(1))
        fees_updated_event = VaultFeesUpdatedEventFactory.build(
            vault=VaultAddresses.VAULT_0, block_number=BlockNumber(1)
        )
        socialized_event = BadDebtSocializedEventFactory.build(
            vault_donor=VaultAddresses.VAULT_1,
            vault_acceptor=VaultAddresses.VAULT_0,
            block_number=BlockNumber(1),
        )

        assert (
            StakingVaultsService._get_event_effective_timestamp(
                minted_event, VaultAddresses.VAULT_0, block_timestamps, seconds_per_slot
            )
            == 100
        )
        assert (
            StakingVaultsService._get_event_effective_timestamp(
                fees_updated_event, VaultAddresses.VAULT_0, block_timestamps, seconds_per_slot
            )
            == 100
        )
        assert (
            StakingVaultsService._get_event_effective_timestamp(
                socialized_event, VaultAddresses.VAULT_0, block_timestamps, seconds_per_slot
            )
            == 100
        )

    @pytest.mark.unit
    def test_decrease_events_use_slot_end(self):
        """Burn/rebalance/write-off/donor events should be effective at slot end."""
        block_timestamps = {BlockNumber(1): 100}
        seconds_per_slot = FeeTestConstants.SECONDS_PER_SLOT

        burned_event = BurnedSharesEventFactory.build(vault=VaultAddresses.VAULT_0, block_number=BlockNumber(1))
        rebalanced_event = VaultRebalancedEventFactory.build(vault=VaultAddresses.VAULT_0, block_number=BlockNumber(1))
        written_off_event = BadDebtWrittenOffEventFactory.build(
            vault=VaultAddresses.VAULT_0, block_number=BlockNumber(1)
        )
        socialized_event = BadDebtSocializedEventFactory.build(
            vault_donor=VaultAddresses.VAULT_0,
            vault_acceptor=VaultAddresses.VAULT_1,
            block_number=BlockNumber(1),
        )

        expected = 100 + seconds_per_slot
        assert (
            StakingVaultsService._get_event_effective_timestamp(
                burned_event, VaultAddresses.VAULT_0, block_timestamps, seconds_per_slot
            )
            == expected
        )
        assert (
            StakingVaultsService._get_event_effective_timestamp(
                rebalanced_event, VaultAddresses.VAULT_0, block_timestamps, seconds_per_slot
            )
            == expected
        )
        assert (
            StakingVaultsService._get_event_effective_timestamp(
                written_off_event, VaultAddresses.VAULT_0, block_timestamps, seconds_per_slot
            )
            == expected
        )
        assert (
            StakingVaultsService._get_event_effective_timestamp(
                socialized_event, VaultAddresses.VAULT_0, block_timestamps, seconds_per_slot
            )
            == expected
        )


class TestGetVaultEventsForFees:
    """Tests for _get_vault_events_for_fees helper."""

    @pytest.mark.unit
    def test_groups_events_and_tracks_connected_vaults(self):
        """Events should be grouped per vault and connected vaults tracked."""
        from_block = BlockNumber(1)
        to_block = BlockNumber(100)

        fee_updated_event = VaultFeesUpdatedEventFactory.build(vault=VaultAddresses.VAULT_0)
        minted_event = MintedSharesEventFactory.build(vault=VaultAddresses.VAULT_1)
        burned_event = BurnedSharesEventFactory.build(vault=VaultAddresses.VAULT_1)
        rebalanced_event = VaultRebalancedEventFactory.build(vault=VaultAddresses.VAULT_2)
        written_off_event = BadDebtWrittenOffEventFactory.build(vault=VaultAddresses.VAULT_2)
        socialized_event = BadDebtSocializedEventFactory.build(
            vault_donor=VaultAddresses.VAULT_0,
            vault_acceptor=VaultAddresses.VAULT_3,
        )
        connected_event = VaultConnectedEventFactory.build(vault=VaultAddresses.VAULT_3)

        vault_hub_mock = MagicMock()
        vault_hub_mock.get_vault_fee_updated_events.return_value = [fee_updated_event]
        vault_hub_mock.get_minted_events.return_value = [minted_event]
        vault_hub_mock.get_burned_events.return_value = [burned_event]
        vault_hub_mock.get_vault_rebalanced_events.return_value = [rebalanced_event]
        vault_hub_mock.get_bad_debt_written_off_to_be_internalized_events.return_value = [written_off_event]
        vault_hub_mock.get_bad_debt_socialized_events.return_value = [socialized_event]
        vault_hub_mock.get_vault_connected_events.return_value = [connected_event]

        service = StakingVaultsService(MagicMock())
        events, connected_vaults = service._get_vault_events_for_fees(vault_hub_mock, from_block, to_block)

        vault_hub_mock.get_vault_fee_updated_events.assert_called_once_with(from_block, to_block)
        vault_hub_mock.get_minted_events.assert_called_once_with(from_block, to_block)
        vault_hub_mock.get_burned_events.assert_called_once_with(from_block, to_block)
        vault_hub_mock.get_vault_rebalanced_events.assert_called_once_with(from_block, to_block)
        vault_hub_mock.get_bad_debt_written_off_to_be_internalized_events.assert_called_once_with(from_block, to_block)
        vault_hub_mock.get_bad_debt_socialized_events.assert_called_once_with(from_block, to_block)
        vault_hub_mock.get_vault_connected_events.assert_called_once_with(from_block, to_block)

        assert fee_updated_event in events[VaultAddresses.VAULT_0]
        assert minted_event in events[VaultAddresses.VAULT_1]
        assert burned_event in events[VaultAddresses.VAULT_1]
        assert rebalanced_event in events[VaultAddresses.VAULT_2]
        assert written_off_event in events[VaultAddresses.VAULT_2]
        assert socialized_event in events[VaultAddresses.VAULT_0]
        assert socialized_event in events[VaultAddresses.VAULT_3]
        assert connected_event in events[VaultAddresses.VAULT_3]
        assert VaultAddresses.VAULT_3 in connected_vaults


class TestCalculateVaultFeeComponents:
    """Tests for _calculate_vault_fee_components helper."""

    @pytest.mark.unit
    def test_no_events_uses_liability_shares(self):
        """No-event path should compute fees off current liability shares."""
        vault_info = VaultInfoFactory.build_with_fees(
            vault=VaultAddresses.VAULT_0,
            liability_shares=FeeTestConstants.LIABILITY_SHARES,
            mintable_st_eth=FeeTestConstants.MINTABLE_STETH,
            infra_fee_bp=FeeTestConstants.INFRA_FEE_BP,
            liquidity_fee_bp=FeeTestConstants.LIQUIDITY_FEE_BP,
            reservation_fee_bp=FeeTestConstants.RESERVATION_FEE_BP,
        )
        time_elapsed_seconds = 10
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
                time_elapsed_seconds=time_elapsed_seconds,
                prev_report_timestamp=0,
                current_report_timestamp=10,
                core_apr_ratio=core_apr_ratio,
                pre_total_pooled_ether=pre_total_pooled_ether,
                pre_total_shares=pre_total_shares,
                block_timestamps={},
                seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT,
            )
        )

        assert infra_fee == StakingVaultsService.calc_fee_value(
            Decimal(FeeTestConstants.VAULT_TOTAL_VALUE),
            time_elapsed_seconds,
            core_apr_ratio,
            FeeTestConstants.INFRA_FEE_BP,
        )
        assert reservation_fee == StakingVaultsService.calc_fee_value(
            Decimal(FeeTestConstants.MINTABLE_STETH),
            time_elapsed_seconds,
            core_apr_ratio,
            FeeTestConstants.RESERVATION_FEE_BP,
        )
        assert liquidity_fee == StakingVaultsService.calc_fee_value(
            minted_steth,
            time_elapsed_seconds,
            core_apr_ratio,
            FeeTestConstants.LIQUIDITY_FEE_BP,
        )
        assert liability_shares == vault_info.liability_shares

    @pytest.mark.unit
    def test_with_events_uses_event_helper(self, monkeypatch):
        """Event path should delegate to _calculate_liquidity_fee_by_events."""
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
                time_elapsed_seconds=10,
                prev_report_timestamp=0,
                current_report_timestamp=10,
                core_apr_ratio=Decimal(1),
                pre_total_pooled_ether=100,
                pre_total_shares=50,
                block_timestamps=block_timestamps,
                seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT,
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
        service._get_start_point_for_fee_calculations = MagicMock(return_value=[prev_report, SlotNumber(0), 0])

        mock_ref_block = MagicMock()
        mock_ref_block.block_number = 7_200
        mock_ref_block.ref_slot = SlotNumber(7_200)

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
                chain_config=MagicMock(genesis_time=0, seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT),
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
        service._get_start_point_for_fee_calculations = MagicMock(return_value=[prev_report, SlotNumber(0), 0])

        blockstamp = MagicMock()
        blockstamp.block_number = 100
        blockstamp.ref_slot = SlotNumber(100)

        w3_mock.eth.get_block.return_value = {"timestamp": 10 * FeeTestConstants.SECONDS_PER_SLOT}

        fees = service.get_vaults_fees(
            blockstamp=blockstamp,
            vaults={vault_adr: vault},
            vaults_total_values={vault_adr: FeeTestConstants.VAULT_TOTAL_VALUE},
            latest_onchain_ipfs_report_data=OnChainIpfsVaultReportDataFactory.build(),
            core_apr_ratio=FeeTestConstants.CORE_APR_RATIO,
            pre_total_pooled_ether=FeeTestConstants.PRE_TOTAL_POOLED_ETHER,
            pre_total_shares=FeeTestConstants.PRE_TOTAL_SHARES,
            frame_config=MagicMock(),
            chain_config=MagicMock(genesis_time=0, seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT),
            current_frame=FrameNumber(0),
        )

        assert fees[vault_adr].prev_fee == 0

    @pytest.mark.unit
    def test_no_events_liquidity_fee(self, mock_vault_hub_events):
        """No events should accrue liquidity fee over the full report interval."""
        vault_adr = VaultAddresses.VAULT_0

        prev_report = MagicMock()
        prev_report.values = [
            MerkleValueFactory.build(
                vault_address=vault_adr,
                fee=0,
                liability_shares=FeeTestConstants.LIABILITY_SHARES,
                max_liability_shares=FeeTestConstants.LIABILITY_SHARES,
            )
        ]

        vault = VaultInfoFactory.build_with_fees(
            vault=vault_adr,
            liability_shares=FeeTestConstants.LIABILITY_SHARES,
            max_liability_shares=FeeTestConstants.LIABILITY_SHARES,
            mintable_st_eth=0,
            infra_fee_bp=0,
            liquidity_fee_bp=FeeTestConstants.LIQUIDITY_FEE_BP,
            reservation_fee_bp=0,
        )

        vault_hub_mock = mock_vault_hub_events()

        w3_mock = MagicMock()
        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.lazy_oracle = MagicMock()

        service = StakingVaultsService(w3_mock)
        service._get_start_point_for_fee_calculations = MagicMock(return_value=[prev_report, SlotNumber(0), 0])

        blockstamp = MagicMock()
        blockstamp.block_number = 1
        blockstamp.ref_slot = SlotNumber(7_200)

        fees = service.get_vaults_fees(
            blockstamp=blockstamp,
            vaults={vault_adr: vault},
            vaults_total_values={vault_adr: 0},
            latest_onchain_ipfs_report_data=OnChainIpfsVaultReportDataFactory.build(),
            core_apr_ratio=FeeTestConstants.CORE_APR_RATIO,
            pre_total_pooled_ether=FeeTestConstants.PRE_TOTAL_POOLED_ETHER,
            pre_total_shares=FeeTestConstants.PRE_TOTAL_SHARES,
            frame_config=MagicMock(),
            chain_config=MagicMock(genesis_time=0, seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT),
            current_frame=FrameNumber(0),
        )

        assert fees[vault_adr].liquidity_fee == 20513697696884909

    @pytest.mark.unit
    def test_fee_elapsed_time_uses_ref_slot_seconds(self, mock_vault_hub_events):
        """Fees should follow ref slot time, not execution block delta."""
        vault_adr = VaultAddresses.VAULT_0

        vault = VaultInfoFactory.build_with_fees(
            vault=vault_adr,
            liability_shares=0,
            max_liability_shares=0,
            mintable_st_eth=0,
            infra_fee_bp=1,
            liquidity_fee_bp=0,
            reservation_fee_bp=0,
        )

        vault_hub_mock = mock_vault_hub_events()

        w3_mock = MagicMock()
        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.lazy_oracle = MagicMock()

        service = StakingVaultsService(w3_mock)
        service._get_start_point_for_fee_calculations = MagicMock(return_value=[None, SlotNumber(100), 10])

        blockstamp = MagicMock()
        blockstamp.block_number = 11
        blockstamp.ref_slot = SlotNumber(102)

        chain_config = MagicMock(genesis_time=0, seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT)

        total_value = SECONDS_IN_YEAR * TOTAL_BASIS_POINTS
        fees = service.get_vaults_fees(
            blockstamp=blockstamp,
            vaults={vault_adr: vault},
            vaults_total_values={vault_adr: total_value},
            latest_onchain_ipfs_report_data=OnChainIpfsVaultReportDataFactory.build(),
            core_apr_ratio=Decimal(1),
            pre_total_pooled_ether=FeeTestConstants.PRE_TOTAL_POOLED_ETHER,
            pre_total_shares=FeeTestConstants.PRE_TOTAL_SHARES,
            frame_config=MagicMock(),
            chain_config=chain_config,
            current_frame=FrameNumber(0),
        )

        assert fees[vault_adr].infra_fee == 2 * FeeTestConstants.SECONDS_PER_SLOT

    @pytest.mark.unit
    def test_fee_elapsed_time_missing_slots_at_start(self, mock_vault_hub_events):
        """Missing slots immediately after the previous report should still accrue fees."""
        vault_adr = VaultAddresses.VAULT_0
        vault = VaultInfoFactory.build_with_fees(
            vault=vault_adr,
            liability_shares=0,
            max_liability_shares=0,
            mintable_st_eth=0,
            infra_fee_bp=1,
            liquidity_fee_bp=0,
            reservation_fee_bp=0,
        )

        vault_hub_mock = mock_vault_hub_events()
        w3_mock = MagicMock()
        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.lazy_oracle = MagicMock()

        service = StakingVaultsService(w3_mock)
        service._get_start_point_for_fee_calculations = MagicMock(return_value=[None, SlotNumber(100), 10])

        blockstamp = MagicMock()
        blockstamp.block_number = 11
        blockstamp.ref_slot = SlotNumber(105)

        prev_report_timestamp = 100 * FeeTestConstants.SECONDS_PER_SLOT
        current_report_timestamp = 105 * FeeTestConstants.SECONDS_PER_SLOT
        time_elapsed_seconds = current_report_timestamp - prev_report_timestamp
        assert time_elapsed_seconds == 5 * FeeTestConstants.SECONDS_PER_SLOT

        total_value = SECONDS_IN_YEAR * TOTAL_BASIS_POINTS
        fees = service.get_vaults_fees(
            blockstamp=blockstamp,
            vaults={vault_adr: vault},
            vaults_total_values={vault_adr: total_value},
            latest_onchain_ipfs_report_data=OnChainIpfsVaultReportDataFactory.build(),
            core_apr_ratio=Decimal(1),
            pre_total_pooled_ether=FeeTestConstants.PRE_TOTAL_POOLED_ETHER,
            pre_total_shares=FeeTestConstants.PRE_TOTAL_SHARES,
            frame_config=MagicMock(),
            chain_config=MagicMock(genesis_time=0, seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT),
            current_frame=FrameNumber(0),
        )

        expected_fee = StakingVaultsService.calc_fee_value(Decimal(total_value), time_elapsed_seconds, Decimal(1), 1)
        assert fees[vault_adr].infra_fee == int(expected_fee)

    @pytest.mark.unit
    def test_fee_elapsed_time_missing_slots_at_end_with_event(self, mock_vault_hub_events):
        """Missing slots after the last event should be included up to the report ref slot."""
        vault_adr = VaultAddresses.VAULT_0
        vault = VaultInfoFactory.build_with_fees(
            vault=vault_adr,
            liability_shares=1,
            max_liability_shares=1,
            mintable_st_eth=0,
            infra_fee_bp=0,
            liquidity_fee_bp=1,
            reservation_fee_bp=0,
        )
        prev_report = MagicMock()
        prev_report.values = [
            MerkleValueFactory.build(
                vault_address=vault_adr,
                fee=0,
                liability_shares=1,
                max_liability_shares=1,
            )
        ]

        fee_event = VaultFeesUpdatedEventFactory.build(
            vault=vault_adr,
            block_number=BlockNumber(10),
            pre_liquidity_fee_bp=2,
        )
        vault_hub_mock = mock_vault_hub_events(fee_updated_events=[fee_event])

        w3_mock = MagicMock()
        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.lazy_oracle = MagicMock()

        service = StakingVaultsService(w3_mock)
        service._get_start_point_for_fee_calculations = MagicMock(return_value=[prev_report, SlotNumber(100), 10])
        service._get_block_timestamps = MagicMock(
            return_value={BlockNumber(10): 102 * FeeTestConstants.SECONDS_PER_SLOT}
        )

        blockstamp = MagicMock()
        blockstamp.block_number = 11
        blockstamp.ref_slot = SlotNumber(110)

        fees = service.get_vaults_fees(
            blockstamp=blockstamp,
            vaults={vault_adr: vault},
            vaults_total_values={vault_adr: 0},
            latest_onchain_ipfs_report_data=OnChainIpfsVaultReportDataFactory.build(),
            core_apr_ratio=Decimal(1),
            pre_total_pooled_ether=SECONDS_IN_YEAR * TOTAL_BASIS_POINTS,
            pre_total_shares=1,
            frame_config=MagicMock(),
            chain_config=MagicMock(genesis_time=0, seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT),
            current_frame=FrameNumber(0),
        )

        event_timestamp = StakingVaultsService._get_event_effective_timestamp(
            fee_event,
            vault_adr,
            {BlockNumber(10): 102 * FeeTestConstants.SECONDS_PER_SLOT},
            FeeTestConstants.SECONDS_PER_SLOT,
        )
        assert event_timestamp == 102 * FeeTestConstants.SECONDS_PER_SLOT

        current_report_timestamp = 110 * FeeTestConstants.SECONDS_PER_SLOT
        prev_report_timestamp = 100 * FeeTestConstants.SECONDS_PER_SLOT
        interval_after_event = current_report_timestamp - event_timestamp
        interval_before_event = event_timestamp - prev_report_timestamp
        assert interval_after_event == 8 * FeeTestConstants.SECONDS_PER_SLOT
        assert interval_before_event == 2 * FeeTestConstants.SECONDS_PER_SLOT

        expected_fee = StakingVaultsService.calc_fee_value(
            Decimal(SECONDS_IN_YEAR * TOTAL_BASIS_POINTS),
            interval_after_event,
            Decimal(1),
            1,
        ) + StakingVaultsService.calc_fee_value(
            Decimal(SECONDS_IN_YEAR * TOTAL_BASIS_POINTS),
            interval_before_event,
            Decimal(1),
            2,
        )
        assert fees[vault_adr].liquidity_fee == int(expected_fee)

    @pytest.mark.unit
    def test_fee_elapsed_time_missing_slots_in_middle(self, mock_vault_hub_events):
        """Gaps between events should still be counted via timestamps/ref slots."""
        vault_adr = VaultAddresses.VAULT_0
        vault = VaultInfoFactory.build_with_fees(
            vault=vault_adr,
            liability_shares=1,
            max_liability_shares=1,
            mintable_st_eth=0,
            infra_fee_bp=0,
            liquidity_fee_bp=1,
            reservation_fee_bp=0,
        )
        prev_report = MagicMock()
        prev_report.values = [
            MerkleValueFactory.build(
                vault_address=vault_adr,
                fee=0,
                liability_shares=1,
                max_liability_shares=1,
            )
        ]

        event_1 = VaultFeesUpdatedEventFactory.build(
            vault=vault_adr,
            block_number=BlockNumber(10),
            pre_liquidity_fee_bp=2,
        )
        event_2 = VaultFeesUpdatedEventFactory.build(
            vault=vault_adr,
            block_number=BlockNumber(20),
            pre_liquidity_fee_bp=3,
        )
        vault_hub_mock = mock_vault_hub_events(fee_updated_events=[event_1, event_2])

        w3_mock = MagicMock()
        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.lazy_oracle = MagicMock()

        service = StakingVaultsService(w3_mock)
        service._get_start_point_for_fee_calculations = MagicMock(return_value=[prev_report, SlotNumber(100), 10])
        service._get_block_timestamps = MagicMock(
            return_value={
                BlockNumber(10): 102 * FeeTestConstants.SECONDS_PER_SLOT,
                BlockNumber(20): 108 * FeeTestConstants.SECONDS_PER_SLOT,
            }
        )

        blockstamp = MagicMock()
        blockstamp.block_number = 21
        blockstamp.ref_slot = SlotNumber(110)

        fees = service.get_vaults_fees(
            blockstamp=blockstamp,
            vaults={vault_adr: vault},
            vaults_total_values={vault_adr: 0},
            latest_onchain_ipfs_report_data=OnChainIpfsVaultReportDataFactory.build(),
            core_apr_ratio=Decimal(1),
            pre_total_pooled_ether=SECONDS_IN_YEAR * TOTAL_BASIS_POINTS,
            pre_total_shares=1,
            frame_config=MagicMock(),
            chain_config=MagicMock(genesis_time=0, seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT),
            current_frame=FrameNumber(0),
        )

        event_1_timestamp = 102 * FeeTestConstants.SECONDS_PER_SLOT
        event_2_timestamp = 108 * FeeTestConstants.SECONDS_PER_SLOT
        current_report_timestamp = 110 * FeeTestConstants.SECONDS_PER_SLOT
        prev_report_timestamp = 100 * FeeTestConstants.SECONDS_PER_SLOT

        assert event_2_timestamp > event_1_timestamp
        assert current_report_timestamp - event_2_timestamp == 2 * FeeTestConstants.SECONDS_PER_SLOT
        assert event_2_timestamp - event_1_timestamp == 6 * FeeTestConstants.SECONDS_PER_SLOT
        assert event_1_timestamp - prev_report_timestamp == 2 * FeeTestConstants.SECONDS_PER_SLOT

        expected_fee = (
            StakingVaultsService.calc_fee_value(
                Decimal(SECONDS_IN_YEAR * TOTAL_BASIS_POINTS),
                current_report_timestamp - event_2_timestamp,
                Decimal(1),
                1,
            )
            + StakingVaultsService.calc_fee_value(
                Decimal(SECONDS_IN_YEAR * TOTAL_BASIS_POINTS),
                event_2_timestamp - event_1_timestamp,
                Decimal(1),
                3,
            )
            + StakingVaultsService.calc_fee_value(
                Decimal(SECONDS_IN_YEAR * TOTAL_BASIS_POINTS),
                event_1_timestamp - prev_report_timestamp,
                Decimal(1),
                2,
            )
        )
        assert fees[vault_adr].liquidity_fee == int(expected_fee)

    @pytest.mark.unit
    def test_fee_elapsed_time_with_empty_prev_ref_slot(self, mock_vault_hub_events):
        """A missing previous ref slot (-1) should still yield a positive interval."""
        vault_adr = VaultAddresses.VAULT_0
        vault = VaultInfoFactory.build_with_fees(
            vault=vault_adr,
            liability_shares=0,
            max_liability_shares=0,
            mintable_st_eth=0,
            infra_fee_bp=1,
            liquidity_fee_bp=0,
            reservation_fee_bp=0,
        )

        vault_hub_mock = mock_vault_hub_events()
        w3_mock = MagicMock()
        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.lazy_oracle = MagicMock()

        service = StakingVaultsService(w3_mock)
        service._get_start_point_for_fee_calculations = MagicMock(return_value=[None, SlotNumber(-1), 0])

        blockstamp = MagicMock()
        blockstamp.block_number = 0
        blockstamp.ref_slot = SlotNumber(0)

        prev_report_timestamp = -1 * FeeTestConstants.SECONDS_PER_SLOT
        current_report_timestamp = 0
        time_elapsed_seconds = current_report_timestamp - prev_report_timestamp
        assert time_elapsed_seconds == FeeTestConstants.SECONDS_PER_SLOT

        total_value = SECONDS_IN_YEAR * TOTAL_BASIS_POINTS
        fees = service.get_vaults_fees(
            blockstamp=blockstamp,
            vaults={vault_adr: vault},
            vaults_total_values={vault_adr: total_value},
            latest_onchain_ipfs_report_data=OnChainIpfsVaultReportDataFactory.build(),
            core_apr_ratio=Decimal(1),
            pre_total_pooled_ether=FeeTestConstants.PRE_TOTAL_POOLED_ETHER,
            pre_total_shares=FeeTestConstants.PRE_TOTAL_SHARES,
            frame_config=MagicMock(),
            chain_config=MagicMock(genesis_time=0, seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT),
            current_frame=FrameNumber(0),
        )

        expected_fee = StakingVaultsService.calc_fee_value(Decimal(total_value), time_elapsed_seconds, Decimal(1), 1)
        assert fees[vault_adr].infra_fee == int(expected_fee)

    @pytest.mark.unit
    def test_raises_if_time_elapsed_negative(self):
        """Reject negative elapsed time between reports."""
        w3_mock = MagicMock()
        service = StakingVaultsService(w3_mock)
        service._get_start_point_for_fee_calculations = MagicMock(return_value=[None, SlotNumber(10), 0])

        blockstamp = MagicMock()
        blockstamp.ref_slot = SlotNumber(9)

        chain_config = MagicMock(genesis_time=0, seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT)

        with pytest.raises(ValueError, match='Negative time/slot interval'):
            service.get_vaults_fees(
                blockstamp=blockstamp,
                vaults={},
                vaults_total_values={},
                latest_onchain_ipfs_report_data=OnChainIpfsVaultReportDataFactory.build(),
                core_apr_ratio=Decimal('0'),
                pre_total_pooled_ether=0,
                pre_total_shares=1,
                frame_config=MagicMock(),
                chain_config=chain_config,
                current_frame=FrameNumber(0),
            )

    @pytest.mark.unit
    def test_no_events_skip_block_timestamp_lookup(self, mock_vault_hub_events):
        """No events should avoid execution block timestamp fetches."""
        vault_adr = VaultAddresses.VAULT_0
        vault = VaultInfoFactory.build_with_fees(
            vault=vault_adr,
            liability_shares=0,
            max_liability_shares=0,
            mintable_st_eth=0,
            infra_fee_bp=0,
            liquidity_fee_bp=0,
            reservation_fee_bp=0,
        )

        vault_hub_mock = mock_vault_hub_events()

        w3_mock = MagicMock()
        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.lazy_oracle = MagicMock()
        w3_mock.eth.get_block = MagicMock()

        service = StakingVaultsService(w3_mock)
        service._get_start_point_for_fee_calculations = MagicMock(return_value=[None, SlotNumber(0), 0])

        blockstamp = MagicMock()
        blockstamp.block_number = 1
        blockstamp.ref_slot = SlotNumber(1)

        service.get_vaults_fees(
            blockstamp=blockstamp,
            vaults={vault_adr: vault},
            vaults_total_values={vault_adr: 0},
            latest_onchain_ipfs_report_data=OnChainIpfsVaultReportDataFactory.build(),
            core_apr_ratio=Decimal('0'),
            pre_total_pooled_ether=0,
            pre_total_shares=1,
            frame_config=MagicMock(),
            chain_config=MagicMock(genesis_time=0, seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT),
            current_frame=FrameNumber(0),
        )

        w3_mock.eth.get_block.assert_not_called()
