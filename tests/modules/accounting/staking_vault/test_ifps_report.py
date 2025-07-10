import pytest

from src.modules.accounting.staking_vaults import StakingVaultsService
from src.modules.accounting.types import IpfsReport
from src.providers.ipfs import CIDv0


@pytest.mark.testnet
@pytest.mark.integration
class TestIpfsReportSmoke:

    def test_get_burned_events(self, web3_integration):
        cid = CIDv0("QmQkmpTStCSJ1gLNVAwNDQDHRgTVGXX2HZ8fG6N1tpAG6q")
        expected_tree_root = "0xb250c9feab479d1ee57f080d689f47e1bd11b74b2316fb0422242c2366a43a39"

        bb = web3_integration.ipfs.fetch(cid)
        tree = IpfsReport.parse_merkle_tree_data(bb)

        sv = StakingVaultsService(web3_integration)

        assert True == sv.is_tree_root_valid(expected_tree_root, tree)
