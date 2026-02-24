from decimal import ROUND_UP, Decimal
from unittest.mock import ANY, MagicMock, patch

import pytest
from eth_typing import BlockNumber
from web3.types import Wei

from src.constants import SECONDS_IN_YEAR, TOTAL_BASIS_POINTS
from src.modules.submodules.types import ChainConfig, FrameConfig
from src.services.staking_vaults import StakingVaultsService
from src.types import FrameNumber, ReferenceBlockStamp, SlotNumber
from src.utils.apr import get_steth_by_shares
from tests.factory.blockstamp import BlockStampFactory
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

# =============================================================================
# Tests
# =============================================================================


@pytest.mark.unit
class TestGetVaultsFees:

    @pytest.fixture
    def service(self, web3, monkeypatch):
        web3.cc = MagicMock()
        web3.lido_contracts.vault_hub = MagicMock()
        web3.lido_contracts.accounting_oracle = MagicMock()
        web3.lido_contracts.lazy_oracle = MagicMock()
        web3.eth.get_block = MagicMock()

        svc = StakingVaultsService(web3)

        fake_blockstamp = MagicMock()
        fake_blockstamp.block_number = 0
        monkeypatch.setattr("src.services.staking_vaults.get_blockstamp", MagicMock(return_value=fake_blockstamp))

        return svc

    @pytest.fixture
    def vault_hub_mock(self):
        mock = MagicMock()
        mock.get_vault_fee_updated_events = MagicMock(return_value=[])
        mock.get_minted_events = MagicMock(return_value=[])
        mock.get_burned_events = MagicMock(return_value=[])
        mock.get_vault_rebalanced_events = MagicMock(return_value=[])
        mock.get_bad_debt_socialized_events = MagicMock(return_value=[])
        mock.get_bad_debt_written_off_to_be_internalized_events = MagicMock(return_value=[])
        mock.get_vault_connected_events = MagicMock(return_value=[])
        return mock

    def make_blockstamp(self, block: int = 10, slot: int = 100) -> ReferenceBlockStamp:
        return ReferenceBlockStamp(
            state_root=MagicMock(),
            slot_number=MagicMock(),
            block_hash=MagicMock(),
            block_number=BlockNumber(block),
            block_timestamp=MagicMock(),
            ref_slot=SlotNumber(slot),
            ref_epoch=MagicMock(),
        )

    def test_zero_time_elapsed_allowed(self, service):
        # Setup
        vault_adr = VaultAddresses.VAULT_0
        vault = VaultInfoFactory.build(vault=vault_adr, liability_shares=0, max_liability_shares=0)
        blockstamp = self.make_blockstamp(block=10, slot=100)

        service.w3.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = blockstamp.ref_slot
        service._get_prev_vault_ipfs_report = MagicMock(return_value=None)
        service._get_vault_events_for_fees = MagicMock(return_value=({}, set()))
        service._calculate_vault_fee_components = MagicMock(return_value=(Decimal(0), Decimal(0), Decimal(0), 0))

        # Act
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

        # Assert
        service._calculate_vault_fee_components.assert_called_once_with(
            vault_address=vault_adr,
            vault_info=vault,
            vault_total_value=0,
            vault_events=[],
            report_interval_seconds=0,
            prev_ref_slot_timestamp=ANY,
            current_ref_slot_timestamp=ANY,
            core_apr_ratio=Decimal(0),
            pre_total_pooled_ether=0,
            pre_total_shares=0,
            block_timestamps={},
        )

        assert fees[vault_adr].prev_fee == 0

    def test_negative_ref_slot_on_first_report(self, service, monkeypatch):
        # initial_epoch - frame_epoches <= 0
        vault_adr = VaultAddresses.VAULT_0
        vault = VaultInfoFactory.build(vault=vault_adr, liability_shares=0, max_liability_shares=0)

        service.w3.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = None
        service._get_prev_vault_ipfs_report = MagicMock(return_value=None)
        service._get_vault_events_for_fees = MagicMock(return_value=({}, set()))
        service._calculate_vault_fee_components = MagicMock(return_value=(Decimal(0), Decimal(0), Decimal(0), 0))

        # Negative prev_slot -> events should be fetched from 0 block
        blockstamp = self.make_blockstamp(block=3 * 32 - 1, slot=3 * 32 - 1)
        monkeypatch.setattr(
            "src.services.staking_vaults.get_blockstamp",
            lambda cc, slot, last_finalized_slot_number: BlockStampFactory.build(block_number=slot),
        )

        service.get_vaults_fees(
            blockstamp=blockstamp,
            vaults={vault_adr: vault},
            vaults_total_values={},
            latest_onchain_ipfs_report_data=OnChainIpfsVaultReportDataFactory.build(report_cid=""),
            core_apr_ratio=Decimal("0"),
            pre_total_pooled_ether=Wei(0),
            pre_total_shares=0,
            frame_config=FrameConfig(initial_epoch=3, epochs_per_frame=5, fast_lane_length_slots=0),
            chain_config=ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0),
            current_frame=FrameNumber(0),
        )

        service._get_vault_events_for_fees.assert_called_once_with(
            vault_hub=service.w3.lido_contracts.vault_hub,
            from_block=1,
            to_block=3 * 32 - 1,
        )

        service._calculate_vault_fee_components.assert_called_once_with(
            vault_address=vault_adr,
            vault_info=vault,
            vault_total_value=0,
            vault_events=[],
            report_interval_seconds=(3 * 32 - 1) * 12,
            prev_ref_slot_timestamp=0,
            current_ref_slot_timestamp=(3 * 32 - 1) * 12,
            core_apr_ratio=Decimal(0),
            pre_total_pooled_ether=0,
            pre_total_shares=0,
            block_timestamps={},
        )

    def test_first_ref_slot_calculate_on_first_report(self, service, monkeypatch):
        # initial_epoch - frame_epoches > 0
        vault_adr = VaultAddresses.VAULT_0
        vault = VaultInfoFactory.build(vault=vault_adr, liability_shares=0, max_liability_shares=0)

        service.w3.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = None
        service._get_prev_vault_ipfs_report = MagicMock(return_value=None)
        service._get_vault_events_for_fees = MagicMock(return_value=({}, set()))
        service._calculate_vault_fee_components = MagicMock(return_value=(Decimal(0), Decimal(0), Decimal(0), 0))

        monkeypatch.setattr(
            "src.services.staking_vaults.get_blockstamp",
            lambda cc, slot, last_finalized_slot_number: BlockStampFactory.build(block_number=slot),
        )

        # First report -> events should be fetched from initial_epoch - frame_epoches
        blockstamp = self.make_blockstamp(block=10 * 32 - 1, slot=10 * 32 - 1)
        service.get_vaults_fees(
            blockstamp=blockstamp,
            vaults={vault_adr: vault},
            vaults_total_values={},
            latest_onchain_ipfs_report_data=OnChainIpfsVaultReportDataFactory.build(report_cid=""),
            core_apr_ratio=Decimal("0"),
            pre_total_pooled_ether=Wei(0),
            pre_total_shares=0,
            frame_config=FrameConfig(initial_epoch=10, epochs_per_frame=5, fast_lane_length_slots=0),
            chain_config=ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0),
            current_frame=FrameNumber(0),
        )

        service._get_vault_events_for_fees.assert_called_once_with(
            vault_hub=service.w3.lido_contracts.vault_hub,
            from_block=(10 - 5) * 32,
            to_block=10 * 32 - 1,
        )

        service._calculate_vault_fee_components.assert_called_once_with(
            vault_address=vault_adr,
            vault_info=vault,
            vault_total_value=0,
            vault_events=[],
            report_interval_seconds=5 * 32 * 12,
            prev_ref_slot_timestamp=(5 * 32 - 1) * 12,
            current_ref_slot_timestamp=(10 * 32 - 1) * 12,
            core_apr_ratio=Decimal(0),
            pre_total_pooled_ether=0,
            pre_total_shares=0,
            block_timestamps={},
        )

    def test_raises_if_liability_shares_mismatch(self, service, vault_hub_mock):
        # Setup
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

        service.w3.lido_contracts.vault_hub = vault_hub_mock
        service.w3.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(7_000)
        service._get_prev_vault_ipfs_report = MagicMock(return_value=prev_report)

        blockstamp = self.make_blockstamp(block=7_200, slot=7_200)

        # Act & Assert
        with pytest.raises(ValueError, match='Wrong liability shares by vault'):
            service.get_vaults_fees(
                blockstamp=blockstamp,
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

    def test_prev_fee_reset_after_reconnect(self, service, vault_hub_mock):
        # Setup
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
        vault_hub_mock.get_vault_connected_events.return_value = connected_events

        service.w3.lido_contracts.vault_hub = vault_hub_mock
        service.w3.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(100)
        service._get_prev_vault_ipfs_report = MagicMock(return_value=prev_report)

        blockstamp = self.make_blockstamp(block=100, slot=100)
        service.w3.eth.get_block.return_value = {"timestamp": 10 * FeeTestConstants.SECONDS_PER_SLOT}

        # Act
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

        # Assert
        assert fees[vault_adr].prev_fee == 0

    def test_no_events_liquidity_fee(self, service, vault_hub_mock):
        # Setup
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

        service.w3.lido_contracts.vault_hub = vault_hub_mock
        prev_ref_slot = SlotNumber(100)
        service.w3.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = prev_ref_slot
        service._get_prev_vault_ipfs_report = MagicMock(return_value=prev_report)

        blockstamp = self.make_blockstamp(block=1, slot=7_200)

        # Act
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

        # Assert
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

    def test_fee_elapsed_time_uses_ref_slot_seconds(self, service, vault_hub_mock):
        # Setup
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

        service.w3.lido_contracts.vault_hub = vault_hub_mock
        service.w3.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(100)
        service._get_prev_vault_ipfs_report = MagicMock(return_value=None)

        blockstamp = self.make_blockstamp(block=11, slot=102)
        chain_config = MagicMock(genesis_time=0, seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT)

        total_value = SECONDS_IN_YEAR * TOTAL_BASIS_POINTS

        # Act
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

        # Assert
        assert fees[vault_adr].infra_fee == 2 * FeeTestConstants.SECONDS_PER_SLOT

    def test_fee_elapsed_time_missing_slots_at_start(self, service, vault_hub_mock):
        # Setup
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

        service.w3.lido_contracts.vault_hub = vault_hub_mock
        service.w3.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(100)
        service._get_prev_vault_ipfs_report = MagicMock(return_value=None)

        blockstamp = self.make_blockstamp(block=11, slot=105)

        prev_report_timestamp = 100 * FeeTestConstants.SECONDS_PER_SLOT
        current_report_timestamp = 105 * FeeTestConstants.SECONDS_PER_SLOT
        time_elapsed_seconds = current_report_timestamp - prev_report_timestamp
        assert time_elapsed_seconds == 5 * FeeTestConstants.SECONDS_PER_SLOT

        total_value = SECONDS_IN_YEAR * TOTAL_BASIS_POINTS

        # Act
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

        # Assert
        expected_fee = StakingVaultsService.calc_fee_value(Decimal(total_value), time_elapsed_seconds, Decimal(1), 1)
        assert fees[vault_adr].infra_fee == int(expected_fee)

    def test_fee_elapsed_time_missing_slots_at_end_with_event(self, service, vault_hub_mock):
        # Setup
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
        vault_hub_mock.get_vault_fee_updated_events.return_value = [fee_event]

        service.w3.lido_contracts.vault_hub = vault_hub_mock
        service.w3.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(100)
        service._get_prev_vault_ipfs_report = MagicMock(return_value=prev_report)

        blockstamp = self.make_blockstamp(block=11, slot=110)

        # Act
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

        # Assert
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

    def test_fee_elapsed_time_missing_slots_in_middle(self, service, vault_hub_mock):
        # Setup
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
        vault_hub_mock.get_vault_fee_updated_events.return_value = [event_1, event_2]

        service.w3.lido_contracts.vault_hub = vault_hub_mock
        service.w3.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(100)
        service._get_prev_vault_ipfs_report = MagicMock(return_value=prev_report)

        blockstamp = self.make_blockstamp(block=21, slot=110)

        # Act
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

        # Assert
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

    def test_raises_if_time_elapsed_negative(self, service):
        # Setup
        service.w3.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(10)
        service._get_prev_vault_ipfs_report = MagicMock(return_value=None)
        service._get_vault_events_for_fees = MagicMock(return_value=({}, set()))

        blockstamp = self.make_blockstamp(block=9, slot=9)
        chain_config = MagicMock(genesis_time=0, seconds_per_slot=FeeTestConstants.SECONDS_PER_SLOT)

        # Act & Assert
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

    def test_no_events_skip_block_timestamp_lookup(self, service, vault_hub_mock):
        # Setup
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

        service.w3.lido_contracts.vault_hub = vault_hub_mock
        service.w3.lido_contracts.accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(1)
        service._get_prev_vault_ipfs_report = MagicMock(return_value=None)

        blockstamp = self.make_blockstamp(block=1, slot=1)

        # Act
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

        # Assert
        service.w3.eth.get_block.assert_not_called()
