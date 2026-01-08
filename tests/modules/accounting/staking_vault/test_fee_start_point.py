from unittest.mock import MagicMock

import pytest
from eth_typing import BlockNumber
from hexbytes import HexBytes

from src.modules.submodules.types import ChainConfig, FrameConfig
from src.services.staking_vaults import StakingVaultsService
from src.types import FrameNumber, ReferenceBlockStamp, SlotNumber
from tests.modules.accounting.staking_vault.conftest import (
    OnChainIpfsVaultReportDataFactory,
    StakingVaultIpfsReportFactory,
)


class TestStartPointForFeeCalculations:
    """Tests for _get_start_point_for_fee_calculations helper."""

    @pytest.mark.unit
    def test_with_prev_ipfs_report(self, monkeypatch):
        """Verifies that when a valid previous IPFS report exists, the start slot for
        fee calculations uses the last processing ref slot. Ensures event scanning
        resumes right after the previously processed block.
        """
        w3_mock = MagicMock()
        accounting_oracle = MagicMock()
        accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(100)
        w3_mock.lido_contracts.accounting_oracle = accounting_oracle
        w3_mock.cc = MagicMock()

        service = StakingVaultsService(w3_mock)

        prev_report = StakingVaultIpfsReportFactory.build(tree=["0xroot"])
        monkeypatch.setattr(service, "get_ipfs_report", MagicMock(return_value=prev_report))
        monkeypatch.setattr(service, "is_tree_root_valid", MagicMock(return_value=True))

        ref_block = MagicMock()
        ref_block.block_number = BlockNumber(777)
        get_blockstamp_mock = MagicMock(return_value=ref_block)
        monkeypatch.setattr("src.services.staking_vaults.get_blockstamp", get_blockstamp_mock)

        blockstamp = ReferenceBlockStamp(
            state_root=MagicMock(),
            slot_number=MagicMock(),
            block_hash=MagicMock(),
            block_number=MagicMock(),
            block_timestamp=MagicMock(),
            ref_slot=SlotNumber(200),
            ref_epoch=MagicMock(),
        )

        latest_data = OnChainIpfsVaultReportDataFactory.build(report_cid="cid", tree_root=HexBytes("0x1234"))
        frame_config = FrameConfig(initial_epoch=1, epochs_per_frame=2, fast_lane_length_slots=0)
        chain_config = ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0)

        result = service._get_start_point_for_fee_calculations(
            blockstamp=blockstamp,
            latest_onchain_ipfs_report_data=latest_data,
            frame_config=frame_config,
            chain_config=chain_config,
            current_frame=FrameNumber(0),
        )

        slots_per_frame = frame_config.epochs_per_frame * chain_config.slots_per_epoch
        get_blockstamp_mock.assert_called_once_with(w3_mock.cc, SlotNumber(100), SlotNumber(100 + slots_per_frame))
        assert result == (prev_report, SlotNumber(100), ref_block.block_number + 1)

    @pytest.mark.unit
    def test_without_prev_ipfs_uses_last_processing_ref_slot(self, monkeypatch):
        """Verifies that when no previous IPFS report exists, the start slot still
        uses the oracle's last processing ref slot. Ensures the oracle ref slot
        defines the earliest safe point for fee events even without IPFS data.
        """
        w3_mock = MagicMock()
        accounting_oracle = MagicMock()
        accounting_oracle.get_last_processing_ref_slot.return_value = SlotNumber(50)
        w3_mock.lido_contracts.accounting_oracle = accounting_oracle
        w3_mock.cc = MagicMock()

        service = StakingVaultsService(w3_mock)

        ref_block = MagicMock()
        ref_block.block_number = BlockNumber(555)
        get_blockstamp_mock = MagicMock(return_value=ref_block)
        monkeypatch.setattr("src.services.staking_vaults.get_blockstamp", get_blockstamp_mock)

        blockstamp = ReferenceBlockStamp(
            state_root=MagicMock(),
            slot_number=MagicMock(),
            block_hash=MagicMock(),
            block_number=MagicMock(),
            block_timestamp=MagicMock(),
            ref_slot=SlotNumber(10),
            ref_epoch=MagicMock(),
        )

        latest_data = OnChainIpfsVaultReportDataFactory.build(report_cid="")
        frame_config = FrameConfig(initial_epoch=1, epochs_per_frame=2, fast_lane_length_slots=0)
        chain_config = ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0)

        result = service._get_start_point_for_fee_calculations(
            blockstamp=blockstamp,
            latest_onchain_ipfs_report_data=latest_data,
            frame_config=frame_config,
            chain_config=chain_config,
            current_frame=FrameNumber(0),
        )

        slots_per_frame = frame_config.epochs_per_frame * chain_config.slots_per_epoch
        get_blockstamp_mock.assert_called_once_with(w3_mock.cc, SlotNumber(50), SlotNumber(50 + slots_per_frame))
        assert result == (None, SlotNumber(50), ref_block.block_number + 1)

    @pytest.mark.unit
    def test_fresh_devnet_uses_initial_epoch(self, monkeypatch):
        """Verifies that when the last processing ref slot is absent, the start slot
        comes from the frame's initial epoch. Ensures devnets have a deterministic
        start anchor even without prior processing history.
        """
        w3_mock = MagicMock()
        accounting_oracle = MagicMock()
        accounting_oracle.get_last_processing_ref_slot.return_value = None
        w3_mock.lido_contracts.accounting_oracle = accounting_oracle
        w3_mock.cc = MagicMock()

        service = StakingVaultsService(w3_mock)

        bs = MagicMock()
        bs.block_number = BlockNumber(999)
        get_blockstamp_mock = MagicMock(return_value=bs)
        monkeypatch.setattr("src.services.staking_vaults.get_blockstamp", get_blockstamp_mock)

        blockstamp = ReferenceBlockStamp(
            state_root=MagicMock(),
            slot_number=MagicMock(),
            block_hash=MagicMock(),
            block_number=MagicMock(),
            block_timestamp=MagicMock(),
            ref_slot=SlotNumber(10),
            ref_epoch=MagicMock(),
        )

        latest_data = OnChainIpfsVaultReportDataFactory.build(report_cid="")
        frame_config = FrameConfig(initial_epoch=10, epochs_per_frame=2, fast_lane_length_slots=0)
        chain_config = ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0)

        result = service._get_start_point_for_fee_calculations(
            blockstamp=blockstamp,
            latest_onchain_ipfs_report_data=latest_data,
            frame_config=frame_config,
            chain_config=chain_config,
            current_frame=FrameNumber(0),
        )

        slots_per_frame = frame_config.epochs_per_frame * chain_config.slots_per_epoch
        initial_ref_slot = frame_config.initial_epoch * chain_config.slots_per_epoch
        get_blockstamp_mock.assert_called_once_with(
            w3_mock.cc, SlotNumber(initial_ref_slot), SlotNumber(int(initial_ref_slot + slots_per_frame))
        )
        assert result == (None, SlotNumber(int(initial_ref_slot) - 1), bs.block_number)
