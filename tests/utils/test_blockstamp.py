from unittest.mock import Mock

import pytest
from eth_utils import add_0x_prefix

from src.types import BlockStamp
from src.utils.blockstamp import BlockstampBuilder
from tests.factory.configs import BlockDetailsResponseFactory


@pytest.mark.unit
class TestGetBlockstampByState:
    @pytest.fixture
    def block_details(self):
        return BlockDetailsResponseFactory.build()

    @pytest.fixture
    def cc(self, block_details):
        return Mock(get_block_details=Mock(return_value=block_details))

    def test_get_blockstamp_by_state__finalized__returns_blockstamp(self, cc, block_details):
        # Act
        bs = BlockstampBuilder(cc).get_blockstamp_by_state('finalized')

        # Assert
        cc.get_block_root.assert_called_once_with('finalized')
        cc.get_block_details.assert_called_once_with(cc.get_block_root.return_value.root)
        execution_payload = block_details.message.body.execution_payload
        assert bs == BlockStamp(
            state_root=block_details.message.state_root,
            slot_number=block_details.message.slot,
            block_hash=add_0x_prefix(execution_payload.block_hash),
            block_number=execution_payload.block_number,
            block_timestamp=execution_payload.timestamp,
        )

    def test_get_blockstamp_by_state__head__requests_head_block(self, cc):
        # Act
        BlockstampBuilder(cc).get_blockstamp_by_state('head')

        # Assert
        cc.get_block_root.assert_called_once_with('head')
