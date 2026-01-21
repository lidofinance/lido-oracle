from decimal import ROUND_UP, Decimal
from unittest.mock import MagicMock, patch

import pytest
from eth_typing import BlockNumber
from web3.types import Wei

from src.constants import SECONDS_IN_YEAR, TOTAL_BASIS_POINTS
from src.modules.submodules.types import ChainConfig, FrameConfig
from src.services.staking_vaults import StakingVaultsService
from src.types import FrameNumber, ReferenceBlockStamp, SlotNumber
from src.utils.apr import get_steth_by_shares
from tests.modules.accounting.staking_vault.conftest import (
    ExtraValueFactory,
    FeeTestConstants,
    MerkleValueFactory,
    OnChainIpfsVaultReportDataFactory,
    VaultAddresses,
    VaultConnectedEventFactory,
    VaultFeesUpdatedEventFactory,
    VaultInfoFactory,
)


@pytest.fixture(autouse=True)
def mock_get_blockstamp(monkeypatch):
    fake_blockstamp = MagicMock()
    fake_blockstamp.block_number = 0
    monkeypatch.setattr("src.services.staking_vaults.get_blockstamp", MagicMock(return_value=fake_blockstamp))
    return fake_blockstamp


@pytest.mark.unit
class TestGetVaultsFees:
    """Tests for get_vaults_fees method."""

    def test_zero_time_elapsed_allowed(self):
        """Verifies that zero time elapsed between reports is handled correctly without
        errors. Ensures same-slot reports don't inflate fees or cause calculation failures.
        """
        vault_adr = VaultAddresses.VAULT_0
        vault = VaultInfoFactory.build(vault=vault_adr, liability_shares=0, max_liability_shares=0)

        w3_mock = MagicMock()
        w3_mock.cc = MagicMock()
        w3_mock.lido_contracts.vault_hub = MagicMock()
        w3_mock.lido_contracts.accounting_oracle = MagicMock()
        w3_mock.lido_contracts.lazy_oracle = MagicMock()

        service = StakingVaultsService(w3_mock)

        blockstamp = ReferenceBlockStamp(
            state_root=MagicMock(),
            slot_number=MagicMock(),
            block_hash=MagicMock(),
            block_number=BlockNumber(10),
            block_timestamp=MagicMock(),
            ref_slot=SlotNumber(100),
            ref_epoch=MagicMock(),
        )

        w3_mock.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = blockstamp.ref_slot
        service._get_prev_vault_ipfs_report = MagicMock(return_value=None)
        service._get_vault_events_for_fees = MagicMock(return_value=({}, set()))
        service._calculate_vault_fee_components = MagicMock(return_value=(Decimal(0), Decimal(0), Decimal(0), 0))

        fees = service.get_vaults_fees(
            blockstamp=blockstamp,
            vaults={vault_adr: vault},
            vaults_total_values={},
            latest_onchain_ipfs_report_data=OnChainIpfsVaultReportDataFactory.build(report_cid=""),
            core_apr_ratio=Decimal("0"),
            pre_total_pooled_ether=Wei(0),
            pre_total_shares=0,
            frame_config=FrameConfig(initial_epoch=0, epochs_per_frame=1, fast_lane_length_slots=0),
            chain_config=ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0),
            current_frame=FrameNumber(0),
        )

        call_kwargs = service._calculate_vault_fee_components.call_args.kwargs
        assert call_kwargs["vault_total_value"] == 0
        assert call_kwargs["report_interval_seconds"] == 0
        assert fees[vault_adr].prev_fee == 0

    def test_raises_if_liability_shares_mismatch(self, mock_vault_hub_events):
        """Verifies that a ValueError is raised when liability shares from current vault
        state don't match the previous report. Ensures state continuity across reports
        and detects missing events or incorrect state tracking.
        """
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
        w3_mock.cc = MagicMock()
        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.accounting_oracle = MagicMock()
        w3_mock.lido_contracts.lazy_oracle = MagicMock()

        service = StakingVaultsService(w3_mock)
        w3_mock.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(7_000)
        service._get_prev_vault_ipfs_report = MagicMock(return_value=prev_report)

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

    def test_prev_fee_reset_after_reconnect(self, mock_vault_hub_events):
        """Verifies that when a vault reconnects, its previous fee is reset to zero.
        Ensures vault reconnection starts a fresh fee tracking period without carrying
        over accumulated fees.
        """
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
        w3_mock.cc = MagicMock()
        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.accounting_oracle = MagicMock()
        w3_mock.lido_contracts.lazy_oracle = MagicMock()

        service = StakingVaultsService(w3_mock)
        w3_mock.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(100)
        service._get_prev_vault_ipfs_report = MagicMock(return_value=prev_report)

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

    def test_no_events_liquidity_fee(self, mock_vault_hub_events):
        """Verifies that when no events occur, liquidity fees accrue continuously over
        the full report interval based on liability shares. Ensures simple time-weighted
        calculations work correctly for continuous fee accrual.
        """
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
        w3_mock.cc = MagicMock()
        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.accounting_oracle = MagicMock()
        w3_mock.lido_contracts.lazy_oracle = MagicMock()

        service = StakingVaultsService(w3_mock)
        prev_ref_slot = SlotNumber(100)
        w3_mock.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = prev_ref_slot
        service._get_prev_vault_ipfs_report = MagicMock(return_value=prev_report)

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

        report_interval_seconds = (blockstamp.ref_slot - prev_ref_slot) * FeeTestConstants.SECONDS_PER_SLOT
        minted_steth = get_steth_by_shares(
            vault.liability_shares,
            FeeTestConstants.PRE_TOTAL_POOLED_ETHER,
            FeeTestConstants.PRE_TOTAL_SHARES,
        )
        expected_fee = StakingVaultsService.calc_fee_value(
            value=minted_steth,
            time_elapsed_seconds=report_interval_seconds,
            core_apr_ratio=FeeTestConstants.CORE_APR_RATIO,
            fee_bp=FeeTestConstants.LIQUIDITY_FEE_BP,
        )
        assert fees[vault_adr].liquidity_fee == int(expected_fee.to_integral_value(ROUND_UP))

    def test_fee_elapsed_time_uses_ref_slot_seconds(self, mock_vault_hub_events):
        """Verifies that fee calculations use reference slot timestamps (consensus time)
        rather than execution block timestamps. Ensures fee calculations align with
        consensus state snapshots and prevent inconsistencies.
        """
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
        w3_mock.cc = MagicMock()
        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.accounting_oracle = MagicMock()
        w3_mock.lido_contracts.lazy_oracle = MagicMock()

        service = StakingVaultsService(w3_mock)
        w3_mock.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(100)
        service._get_prev_vault_ipfs_report = MagicMock(return_value=None)

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

    def test_fee_elapsed_time_missing_slots_at_start(self, mock_vault_hub_events):
        """Verifies that missing slots between reports don't reduce fee accrual, which
        is based on slot time difference rather than block presence. Ensures vaults are
        fairly compensated for time even when block proposals are missed.
        """
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
        w3_mock.cc = MagicMock()
        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.accounting_oracle = MagicMock()
        w3_mock.lido_contracts.lazy_oracle = MagicMock()

        service = StakingVaultsService(w3_mock)
        w3_mock.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(100)
        service._get_prev_vault_ipfs_report = MagicMock(return_value=None)

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

    def test_fee_elapsed_time_missing_slots_at_end_with_event(self, mock_vault_hub_events):
        """Verifies that missing slots after the last event are still included in fee
        accrual up to the report ref slot. Ensures accurate fee calculation continues
        until the report snapshot time regardless of missing blocks.
        """
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
        w3_mock.cc = MagicMock()
        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.accounting_oracle = MagicMock()
        w3_mock.lido_contracts.lazy_oracle = MagicMock()

        service = StakingVaultsService(w3_mock)
        w3_mock.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(100)
        service._get_prev_vault_ipfs_report = MagicMock(return_value=prev_report)

        blockstamp = MagicMock()
        blockstamp.block_number = 11
        blockstamp.ref_slot = SlotNumber(110)

        with patch(
            "src.services.staking_vaults.get_block_timestamps",
            return_value={BlockNumber(10): 102 * FeeTestConstants.SECONDS_PER_SLOT},
        ):
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

        # Event timestamp is the block timestamp directly
        event_timestamp = 102 * FeeTestConstants.SECONDS_PER_SLOT

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

    def test_fee_elapsed_time_missing_slots_in_middle(self, mock_vault_hub_events):
        """Verifies that gaps between events (due to missing slots) are still counted
        in fee calculations based on ref slot timestamps. Ensures correct fee totals
        even when blocks are missing between events.
        """
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
        w3_mock.cc = MagicMock()
        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.accounting_oracle = MagicMock()
        w3_mock.lido_contracts.lazy_oracle = MagicMock()

        service = StakingVaultsService(w3_mock)
        w3_mock.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(100)
        service._get_prev_vault_ipfs_report = MagicMock(return_value=prev_report)

        blockstamp = MagicMock()
        blockstamp.block_number = 21
        blockstamp.ref_slot = SlotNumber(110)

        with patch(
            "src.services.staking_vaults.get_block_timestamps",
            return_value={
                BlockNumber(10): 102 * FeeTestConstants.SECONDS_PER_SLOT,
                BlockNumber(20): 108 * FeeTestConstants.SECONDS_PER_SLOT,
            },
        ):
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

    def test_raises_if_time_elapsed_negative(self):
        """Verifies that a ValueError is raised when current ref slot is before the
        previous ref slot. Ensures negative time intervals are detected early to prevent
        invalid fee calculations from incorrect state tracking.
        """
        w3_mock = MagicMock()
        w3_mock.cc = MagicMock()
        w3_mock.lido_contracts.vault_hub = MagicMock()
        w3_mock.lido_contracts.accounting_oracle = MagicMock()
        service = StakingVaultsService(w3_mock)
        w3_mock.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(10)
        service._get_prev_vault_ipfs_report = MagicMock(return_value=None)
        service._get_vault_events_for_fees = MagicMock(return_value=({}, set()))

        blockstamp = MagicMock()
        blockstamp.ref_slot = SlotNumber(9)

        chain_config = MagicMock(genesis_time=0, seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT)

        with pytest.raises(ValueError, match='Negative report interval'):
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

    def test_no_events_skip_block_timestamp_lookup(self, mock_vault_hub_events):
        """Verifies that when no events occur, execution block timestamp fetches are
        skipped. Ensures performance optimization by avoiding expensive RPC calls when
        ref slot timestamps are sufficient.
        """
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
        w3_mock.cc = MagicMock()
        w3_mock.lido_contracts.vault_hub = vault_hub_mock
        w3_mock.lido_contracts.accounting_oracle = MagicMock()
        w3_mock.lido_contracts.lazy_oracle = MagicMock()
        w3_mock.eth.get_block = MagicMock()

        service = StakingVaultsService(w3_mock)
        w3_mock.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(1)
        service._get_prev_vault_ipfs_report = MagicMock(return_value=None)

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
