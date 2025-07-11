import pytest
from eth_typing import HexStr

from src.services.staking_vaults import StakingVaultsService
from src.modules.accounting.types import StakingVaultIpfsReport
from src.providers.ipfs import CIDv0
from src.types import SlotNumber
from src.utils.slot import get_blockstamp


@pytest.mark.testnet
@pytest.mark.integration
class TestIpfsReportSmoke:

    def test_ipfs_report_valid(self, web3_integration):
        cid = CIDv0("QmQkmpTStCSJ1gLNVAwNDQDHRgTVGXX2HZ8fG6N1tpAG6q")
        expected_tree_root = "0xb250c9feab479d1ee57f080d689f47e1bd11b74b2316fb0422242c2366a43a39"

        bb = web3_integration.ipfs.fetch(cid)
        tree = StakingVaultIpfsReport.parse_merkle_tree_data(bb)

        sv = StakingVaultsService(web3_integration)

        assert True == sv.is_tree_root_valid(expected_tree_root, tree)

    def test_ipfs_window(self, web3_integration):
        sv = StakingVaultsService(web3_integration)
        latest_onchain_ipfs_report_data = sv.get_latest_onchain_ipfs_report_data(block_identifier='latest')
        bb = web3_integration.ipfs.fetch(latest_onchain_ipfs_report_data.report_cid)
        tree = StakingVaultIpfsReport.parse_merkle_tree_data(bb)

        last_processing_ref_slot = web3_integration.lido_contracts.accounting_oracle.get_last_processing_ref_slot(block_identifier=HexStr('latest'))

        if last_processing_ref_slot:
            ref_block = get_blockstamp(
                web3_integration.cc, last_processing_ref_slot, SlotNumber(int(last_processing_ref_slot))
            )

            assert tree.block_number == ref_block.block_number
            assert tree.ref_slot == ref_block.slot_number

        latest_onchain_ipfs_report_data_2 = sv.get_latest_onchain_ipfs_report_data(block_identifier=HexStr(tree.block_hash))
        bb_2 = web3_integration.ipfs.fetch(latest_onchain_ipfs_report_data_2.report_cid)
        tree_2 = StakingVaultIpfsReport.parse_merkle_tree_data(bb_2)

        assert tree_2.block_number != tree.block_number