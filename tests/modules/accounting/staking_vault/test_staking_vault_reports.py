"""
IPFS report and start point calculation tests.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from eth_typing import BlockNumber, HexStr
from web3.types import Timestamp

from src.modules.common.types import ChainConfig, FrameConfig
from src.providers.consensus.types import (
    BeaconBlockBody,
    BlockDetailsResponse,
    BlockMessage,
    ExecutionPayload,
    SyncAggregate,
)
from src.services.staking_vaults import StakingVaultsService
from src.types import (
    BlockHash,
    EpochNumber,
    FrameNumber,
    ReferenceBlockStamp,
    SlotNumber,
    StateRoot,
)
from tests.modules.accounting.staking_vault.conftest import (
    OnChainIpfsVaultReportDataFactory,
    StakingVaultIpfsReportFactory,
)


class TestGetIpfsReport:
    """Tests for get_ipfs_report method."""

    @pytest.mark.unit
    def test_get_ipfs_report_success(self):
        """Test successful IPFS report retrieval."""
        mock_fetched_bytes = (
            b'{"format": "standard-v1", "leafEncoding": ["address", "uint256", "uint256", "uint256", '
            b'"int256"], "tree": ['
            b'"0x7ca488c27e66ddc3fb44b8cc14e72181b71d420ed65f5b77d6da1ca329b4f3c1"], "values": [{'
            b'"value": ["0x1234567890abcdef1234567890abcdef12345678", "1000000000000000000", '
            b'"1000", "2880000000000000000000", "2880000000000000000000", "5555"], "treeIndex": 0}], '
            b'"refSlot": 123450, "blockHash": "0xabc123", "blockNumber": 789654, "timestamp": 1601481472, '
            b'"extraValues": {"0x1234567890abcdef1234567890abcdef12345678": {"inOutDelta": '
            b'"1234567890000000000", "prevFee": "400", "infraFee": "100", "liquidityFee": "200", '
            b'"reservationFee": "300"}}, "prevTreeCID": "prev_tree_cid", "leafIndexToData": {'
            b'"vaultAddress": 0, "totalValueWei": 1, "fee": 2, "liabilityShares": 3, '
            b'"slashingReserve": 4}}'
        )

        w3_mock = MagicMock()
        w3_mock.ipfs.fetch.return_value = mock_fetched_bytes

        service = StakingVaultsService(w3_mock)
        result = service.get_ipfs_report('QmMockCID123', FrameNumber(0))

        assert result.tree[0] == '0x7ca488c27e66ddc3fb44b8cc14e72181b71d420ed65f5b77d6da1ca329b4f3c1'

    @pytest.mark.unit
    def test_get_ipfs_report_empty_cid_raises(self):
        """Test that empty CID raises ValueError."""
        service = StakingVaultsService(MagicMock())

        with pytest.raises(ValueError, match="Arg ipfs_report_cid could not be ''"):
            service.get_ipfs_report('', FrameNumber(0))


class TestGetStartPointForFeeCalculations:
    """Tests for _get_start_point_for_fee_calculations method."""

    @pytest.fixture
    def blockstamp(self):
        """Create a test blockstamp."""
        return ReferenceBlockStamp(
            state_root=StateRoot(HexStr('0xabcabc')),
            slot_number=SlotNumber(1_234),
            block_hash=BlockHash(HexStr('0xdeadbeef')),
            block_number=BlockNumber(4_321),
            block_timestamp=Timestamp(1_690_000_000),
            ref_slot=SlotNumber(1_230),
            ref_epoch=EpochNumber(40),
        )

    @pytest.fixture
    def frame_config(self):
        """Create a test frame config."""
        return FrameConfig(initial_epoch=10, epochs_per_frame=2, fast_lane_length_slots=16)

    @pytest.fixture
    def chain_config(self):
        """Create a test chain config."""
        return ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=1_600_000_000)

    @pytest.mark.unit
    def test_invalid_tree_root_raises(self, blockstamp, frame_config, chain_config):
        """Test that invalid tree root raises ValueError."""
        ipfs_data = OnChainIpfsVaultReportDataFactory.build(
            tree_root=b'\xab\xcd\xef',
            report_cid='cid123',
        )

        fake_prev_report = StakingVaultIpfsReportFactory.build(tree=['0xWRONGROOT'])

        w3_mock = MagicMock()
        w3_mock.cc = MagicMock()
        accounting_oracle_mock = MagicMock()
        accounting_oracle_mock.get_last_processing_ref_slot.return_value = SlotNumber(6_400)
        w3_mock.lido_contracts.accounting_oracle = accounting_oracle_mock

        service = StakingVaultsService(w3_mock)
        service.get_ipfs_report = MagicMock(return_value=fake_prev_report)
        service.is_tree_root_valid = MagicMock(return_value=False)

        with pytest.raises(ValueError) as exc_info:
            service._get_start_point_for_fee_calculations(
                blockstamp, ipfs_data, frame_config, chain_config, FrameNumber(0)
            )

        expected_hex = '0x' + ipfs_data.tree_root.hex()
        assert f'Expected: {expected_hex}' in str(exc_info.value)

    @pytest.mark.unit
    def test_no_ipfs_but_has_oracle_data(self, blockstamp, frame_config, chain_config):
        """Test start point calculation when no IPFS report but oracle data exists."""
        ipfs_data = OnChainIpfsVaultReportDataFactory.build(
            tree_root=b'',
            report_cid='',
        )

        expected_block_number = BlockNumber(5_000)

        w3_mock = MagicMock()
        w3_mock.cc = MagicMock()
        w3_mock.cc.get_block_details.return_value = BlockDetailsResponse(
            message=BlockMessage(
                slot=MagicMock(),
                proposer_index=MagicMock(),
                parent_root=MagicMock(),
                state_root=MagicMock(),
                body=BeaconBlockBody(
                    execution_payload=ExecutionPayload(
                        parent_hash=MagicMock(),
                        block_number=expected_block_number,
                        timestamp=MagicMock(),
                        block_hash=BlockHash(HexStr('0x0abc1234')),
                    ),
                    attestations=MagicMock(),
                    sync_aggregate=SyncAggregate(sync_committee_bits=MagicMock()),
                ),
            ),
            signature=MagicMock(),
        )

        accounting_oracle_mock = MagicMock()
        accounting_oracle_mock.get_last_processing_ref_slot.return_value = SlotNumber(6_400)
        w3_mock.lido_contracts.accounting_oracle = accounting_oracle_mock

        service = StakingVaultsService(w3_mock)

        prev_report, block_number = service._get_start_point_for_fee_calculations(
            blockstamp, ipfs_data, frame_config, chain_config, FrameNumber(0)
        )

        assert prev_report is None
        assert block_number == expected_block_number + 1

    @pytest.mark.unit
    def test_fresh_devnet_case(self, blockstamp, frame_config, chain_config):
        """Test start point calculation for fresh devnet (no previous reports)."""
        ipfs_data = OnChainIpfsVaultReportDataFactory.build(
            tree_root=b'\xab\xcd\xef',
            report_cid='',
        )

        expected_block_number = BlockNumber(6_000)

        w3_mock = MagicMock()
        w3_mock.cc = MagicMock()
        w3_mock.cc.get_block_details.return_value = BlockDetailsResponse(
            message=BlockMessage(
                slot=MagicMock(),
                proposer_index=MagicMock(),
                parent_root=MagicMock(),
                state_root=MagicMock(),
                body=BeaconBlockBody(
                    execution_payload=ExecutionPayload(
                        parent_hash=MagicMock(),
                        block_number=expected_block_number,
                        timestamp=MagicMock(),
                        block_hash=BlockHash(HexStr('0x0abc1234')),
                    ),
                    attestations=MagicMock(),
                    sync_aggregate=SyncAggregate(sync_committee_bits=MagicMock()),
                ),
            ),
            signature=MagicMock(),
        )

        accounting_oracle_mock = MagicMock()
        accounting_oracle_mock.get_last_processing_ref_slot.return_value = None
        w3_mock.lido_contracts.accounting_oracle = accounting_oracle_mock

        service = StakingVaultsService(w3_mock)

        prev_report, block_number = service._get_start_point_for_fee_calculations(
            blockstamp, ipfs_data, frame_config, chain_config, FrameNumber(0)
        )

        assert prev_report is None
        assert block_number == expected_block_number

    @pytest.mark.unit
    def test_prev_ipfs_report_branch_shifts_block(self, blockstamp, frame_config, chain_config, monkeypatch):
        """When previous IPFS exists, start block should be ref_block + 1."""
        ipfs_data = OnChainIpfsVaultReportDataFactory.build(
            tree_root=b'\x01',
            report_cid='cid123',
        )

        prev_report = StakingVaultIpfsReportFactory.build(tree=['0xabc'])

        w3_mock = MagicMock()
        w3_mock.cc = MagicMock()
        accounting_oracle_mock = MagicMock()
        accounting_oracle_mock.get_last_processing_ref_slot.return_value = SlotNumber(64)
        w3_mock.lido_contracts.accounting_oracle = accounting_oracle_mock

        service = StakingVaultsService(w3_mock)
        service.get_ipfs_report = MagicMock(return_value=prev_report)
        service.is_tree_root_valid = MagicMock(return_value=True)

        fake_ref_block = SimpleNamespace(block_number=500)
        monkeypatch.setattr(
            'src.services.staking_vaults.get_blockstamp',
            lambda *args, **kwargs: fake_ref_block,
        )

        report, block_number = service._get_start_point_for_fee_calculations(
            blockstamp, ipfs_data, frame_config, chain_config, FrameNumber(0)
        )

        assert report is prev_report
        assert block_number == fake_ref_block.block_number + 1
        service.is_tree_root_valid.assert_called_once()
