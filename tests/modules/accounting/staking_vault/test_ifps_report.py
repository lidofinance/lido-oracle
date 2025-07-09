import pytest

from src.modules.accounting.staking_vaults import StakingVaults
from src.providers.ipfs import CIDv0


@pytest.mark.testnet
@pytest.mark.integration
class TestIpfsReportSmoke:

    def test_get_burned_events(self, web3_integration):
        cid = CIDv0("QmepSgVe53jH2nyWZS4wsB9CQwFjApN1319KvN1fqjwYqr")
        expected_tree_root = "0xcf8af6f8f5faecb3fb3e0b2a680908a21b3dbc2cfd05c6d514708bf6ce3b8200"
        bb = web3_integration.ipfs.fetch(cid)

        sv = StakingVaults(web3_integration)
        merkle_tree_data = sv.parse_merkle_tree_data(bb)

        assert merkle_tree_data.tree[0] == expected_tree_root
        assert True == sv.is_tree_root_valid(expected_tree_root, merkle_tree_data)