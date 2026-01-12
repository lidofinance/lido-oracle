import pytest
from eth_typing import HexStr

from src.modules.accounting.types import StakingVaultIpfsReport
from src.providers.ipfs import CIDv0
from src.services.staking_vaults import StakingVaultsService
from src.types import FrameNumber, SlotNumber
from src.utils.slot import get_blockstamp


@pytest.mark.testnet
@pytest.mark.integration
class TestIpfsReportSmoke:

    def test_ipfs_report_valid(self, web3_integration):
        cid = CIDv0("QmYnQ9gCriLj29uWC6DC3yFm6gYXNEAkMoHLjtJun8ASeQ")
        expected_tree_root = "0x82d726a060e4133328fb77dac69cfd84e14bb66fb0fd1b2c99ba058efb2f5a30"

        bb = web3_integration.ipfs.fetch(cid, FrameNumber(0))
        tree = StakingVaultIpfsReport.parse_merkle_tree_data(bb)

        sv = StakingVaultsService(web3_integration)

        assert True == sv.is_tree_root_valid(expected_tree_root, tree)

    def test_ipfs_window(self, web3_integration):
        sv = StakingVaultsService(web3_integration)

        block_hash = HexStr('0x4a45cce03c6c8b1bf287454f3b2237238155fc326337ddcf10c0aa1a36ad95f3')
        latest_onchain_ipfs_report_data = sv.get_latest_onchain_ipfs_report_data(block_identifier=block_hash)
        bb = web3_integration.ipfs.fetch(latest_onchain_ipfs_report_data.report_cid, FrameNumber(0))
        tree = StakingVaultIpfsReport.parse_merkle_tree_data(bb)

        last_processing_ref_slot = web3_integration.lido_contracts.accounting_oracle.get_last_processing_ref_slot(
            block_identifier=block_hash
        )

        if last_processing_ref_slot:
            ref_block = get_blockstamp(
                web3_integration.cc, last_processing_ref_slot, SlotNumber(int(last_processing_ref_slot))
            )

            assert tree.block_number == ref_block.block_number
            assert tree.ref_slot == ref_block.slot_number

        latest_onchain_ipfs_report_data_2 = sv.get_latest_onchain_ipfs_report_data(
            block_identifier=HexStr(tree.block_hash)
        )

        bb_2 = web3_integration.ipfs.fetch(latest_onchain_ipfs_report_data_2.report_cid, FrameNumber(0))
        tree_2 = StakingVaultIpfsReport.parse_merkle_tree_data(bb_2)

        assert tree_2.block_number != tree.block_number
