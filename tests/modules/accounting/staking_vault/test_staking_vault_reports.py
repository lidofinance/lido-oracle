from unittest.mock import MagicMock

import pytest

from src.services.staking_vaults import StakingVaultsService
from src.types import FrameNumber


class TestGetIpfsReport:
    """Tests for get_ipfs_report method."""

    @pytest.mark.unit
    def test_get_ipfs_report_success(self):
        """Verifies that IPFS reports are correctly fetched and parsed from IPFS using
        a CID. Ensures the report structure is correctly deserialized with tree roots
        and vault values.
        """
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
        """Verifies that a ValueError is raised when attempting to fetch an IPFS report
        with an empty CID. Ensures invalid CIDs are rejected before attempting IPFS queries.
        """
        service = StakingVaultsService(MagicMock())

        with pytest.raises(ValueError, match="Arg ipfs_report_cid could not be ''"):
            service.get_ipfs_report('', FrameNumber(0))
