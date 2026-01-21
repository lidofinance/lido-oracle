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


@pytest.mark.unit
class TestCalculateLiquidityFeeByEvents:
    """Tests for _calculate_liquidity_fee_by_events static method."""

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
            prev_ref_slot_timestamp=0,
            current_ref_slot_timestamp=7_200 * FeeTestConstants.SECONDS_PER_SLOT,
            pre_total_pooled_ether=FeeTestConstants.PRE_TOTAL_POOLED_ETHER,
            pre_total_shares=FeeTestConstants.PRE_TOTAL_SHARES,
            core_apr_ratio=FeeTestConstants.CORE_APR_RATIO,
            block_timestamps={
                BlockNumber(3_600): 3_600 * FeeTestConstants.SECONDS_PER_SLOT,
                BlockNumber(3_700): 3_700 * FeeTestConstants.SECONDS_PER_SLOT,
                BlockNumber(3_200): 3_200 * FeeTestConstants.SECONDS_PER_SLOT,
            },
        )

        expected_fee = Decimal('16995441781507364.3604745483')
        expected_shares = 2_879_999_910_015_672_558_976

        assert result == (expected_fee, expected_shares)

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
            prev_ref_slot_timestamp=0,
            current_ref_slot_timestamp=20,
            pre_total_pooled_ether=Wei(1),
            pre_total_shares=1,
            core_apr_ratio=Decimal(1),
            block_timestamps={BlockNumber(1): 10},
        )

        expected_fee = StakingVaultsService.calc_fee_value(Decimal(10), 10, Decimal(1), 650) + (
            StakingVaultsService.calc_fee_value(Decimal(10), 10, Decimal(1), 100)
        )
        assert fee == expected_fee
        assert shares == 10

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
                prev_ref_slot_timestamp=100 * FeeTestConstants.SECONDS_PER_SLOT,
                current_ref_slot_timestamp=110 * FeeTestConstants.SECONDS_PER_SLOT,
                pre_total_pooled_ether=Wei(1_000_000_000_000_000_000_000),
                pre_total_shares=1_000_000_000_000_000_000_000,
                core_apr_ratio=Decimal('0.10'),
                block_timestamps={
                    BlockNumber(101): 101 * FeeTestConstants.SECONDS_PER_SLOT,
                    BlockNumber(105): 105 * FeeTestConstants.SECONDS_PER_SLOT,
                },
            )

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

        with pytest.raises(ValueError, match='Negative event interval'):
            StakingVaultsService._calculate_liquidity_fee_by_events(
                vault_address=vault_adr,
                liability_shares=1,
                liquidity_fee_bp=TOTAL_BASIS_POINTS,
                vault_events=vault_events,
                prev_ref_slot_timestamp=0,
                current_ref_slot_timestamp=1,
                pre_total_pooled_ether=Wei(1),
                pre_total_shares=1,
                core_apr_ratio=Decimal(1),
                block_timestamps={BlockNumber(1): 10},
            )

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
            prev_ref_slot_timestamp=0,
            current_ref_slot_timestamp=100,
            pre_total_pooled_ether=Wei(1),
            pre_total_shares=1,
            core_apr_ratio=Decimal(0),
            block_timestamps={BlockNumber(1): 0},
        )

        assert liability_shares == 15

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
            prev_ref_slot_timestamp=0,
            current_ref_slot_timestamp=100,
            pre_total_pooled_ether=Wei(1),
            pre_total_shares=1,
            core_apr_ratio=Decimal(0),
            block_timestamps={BlockNumber(1): 0},
        )

        assert liability_shares == 27

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
            prev_ref_slot_timestamp=0,
            current_ref_slot_timestamp=100,
            pre_total_pooled_ether=Wei(1),
            pre_total_shares=1,
            core_apr_ratio=Decimal(0),
            block_timestamps={BlockNumber(1): 0},
        )

        assert liability_shares == 21
