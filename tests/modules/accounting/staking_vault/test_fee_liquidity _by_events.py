from decimal import Decimal

import pytest
from eth_typing import BlockNumber
from web3.types import Wei

from src.constants import TOTAL_BASIS_POINTS
from src.services.staking_vaults import StakingVaultsService
from tests.modules.accounting.staking_vault.conftest import (
    BadDebtSocializedEventFactory,
    BadDebtWrittenOffEventFactory,
    BurnedSharesEventFactory,
    FeeTestConstants,
    MintedSharesEventFactory,
    VaultAddresses,
    VaultConnectedEventFactory,
    VaultFeesUpdatedEventFactory,
    VaultRebalancedEventFactory,
)


class TestCalculateLiquidityFeeByEvents:
    """Tests for _calculate_liquidity_fee_by_events static method."""

    @pytest.mark.unit
    def test_with_events(self):
        """Verifies liquidity fee calculation correctly processes mint, burn, and fee update
        events, computing fees for each time interval between state changes. Ensures accurate
        fee accrual when vault state changes mid-period using time-weighted calculations.
        """
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
        """Verifies that multiple fee update events in the same block are processed in log
        index order, ensuring deterministic fee calculation. Checks that transaction ordering
        within a block is correctly handled for state changes.
        """
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
        """Verifies that a ValueError is raised when a vault connection event occurs with
        non-zero liability shares. Ensures vault connections only happen during initial
        setup, preventing fee calculation errors from invalid state transitions.
        """
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
        """Verifies that mint and burn events in the same block accrue fees for the full
        slot duration based on effective timestamps. Ensures fees are calculated correctly
        even when shares are held briefly within a single block.
        """
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
        """Verifies that a ValueError is raised when an event's block timestamp is missing
        from the timestamp mapping. Ensures fee calculations have all required timing data
        and fails fast on incomplete event data.
        """
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
        """Verifies that events with timestamps after the current report timestamp are
        rejected with a ValueError. Ensures fee calculations remain historical and prevents
        forward-looking calculations that would cause temporal inconsistencies.
        """
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
        """Verifies that bad debt socialization events apply different effective timestamps
        to donor (slot end) and acceptor (slot start) vaults. Ensures correct fee attribution
        where donor accrues fees before losing shares and acceptor accrues fees after gaining shares.
        """
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

    @pytest.mark.unit
    def test_rebalanced_event_increases_liability_shares_backwards(self):
        """Verifies that VaultRebalancedEvent increases liability_shares by shares_burned
        when processing events in reverse order. Ensures backward reconstruction correctly
        restores pre-event liability for accurate fee calculations.
        """
        event = VaultRebalancedEventFactory.build(
            vault=VaultAddresses.VAULT_0,
            block_number=BlockNumber(1),
            shares_burned=5,
        )

        _, liability_shares = StakingVaultsService._calculate_liquidity_fee_by_events(
            vault_address=VaultAddresses.VAULT_0,
            liability_shares=10,
            liquidity_fee_bp=0,
            vault_events=[event],
            prev_report_timestamp=0,
            current_report_timestamp=100,
            pre_total_pooled_ether=Wei(1),
            pre_total_shares=1,
            core_apr_ratio=Decimal(0),
            block_timestamps={BlockNumber(1): 0},
            seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT,
        )

        assert liability_shares == 15

    @pytest.mark.unit
    def test_written_off_event_increases_liability_shares_backwards(self):
        """Verifies that BadDebtWrittenOffEvent adds bad_debt_shares to liability_shares
        when processing events in reverse order. Ensures the pre-event liability baseline
        is correctly restored for accurate fee calculations.
        """
        event = BadDebtWrittenOffEventFactory.build(
            vault=VaultAddresses.VAULT_0,
            block_number=BlockNumber(1),
            bad_debt_shares=7,
        )

        _, liability_shares = StakingVaultsService._calculate_liquidity_fee_by_events(
            vault_address=VaultAddresses.VAULT_0,
            liability_shares=20,
            liquidity_fee_bp=0,
            vault_events=[event],
            prev_report_timestamp=0,
            current_report_timestamp=100,
            pre_total_pooled_ether=Wei(1),
            pre_total_shares=1,
            core_apr_ratio=Decimal(0),
            block_timestamps={BlockNumber(1): 0},
            seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT,
        )

        assert liability_shares == 27

    @pytest.mark.unit
    def test_socialized_acceptor_decreases_liability_shares_backwards(self):
        """Verifies that BadDebtSocializedEvent reduces liability_shares for the acceptor
        when processing events in reverse order. Ensures reverse traversal correctly
        undoes the acceptor's share increase for accurate fee calculations.
        """
        event = BadDebtSocializedEventFactory.build(
            vault_donor=VaultAddresses.VAULT_1,
            vault_acceptor=VaultAddresses.VAULT_0,
            block_number=BlockNumber(1),
            bad_debt_shares=9,
        )

        _, liability_shares = StakingVaultsService._calculate_liquidity_fee_by_events(
            vault_address=VaultAddresses.VAULT_0,
            liability_shares=30,
            liquidity_fee_bp=0,
            vault_events=[event],
            prev_report_timestamp=0,
            current_report_timestamp=100,
            pre_total_pooled_ether=Wei(1),
            pre_total_shares=1,
            core_apr_ratio=Decimal(0),
            block_timestamps={BlockNumber(1): 0},
            seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT,
        )

        assert liability_shares == 21
