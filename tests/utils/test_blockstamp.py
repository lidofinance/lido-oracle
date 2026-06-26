from unittest.mock import Mock

import pytest
from eth_utils import add_0x_prefix

from src.types import BlockStamp
from src.utils.blockstamp import BlockstampBuilder, build_blockstamp
from tests.factory.configs import BlockDetailsResponseFactory


@pytest.mark.unit
class TestBuildBlockstamp:
    @pytest.fixture
    def block_details(self):
        return BlockDetailsResponseFactory.build()

    def test_build_blockstamp__with_execution_payload__returns_blockstamp(self, block_details):
        bs = build_blockstamp(block_details)

        execution_payload = block_details.message.body.execution_payload
        assert bs == BlockStamp(
            state_root=block_details.message.state_root,
            slot_number=block_details.message.slot,
            block_hash=add_0x_prefix(execution_payload.block_hash),
            block_number=execution_payload.block_number,
            block_timestamp=execution_payload.timestamp,
        )

    def test_build_blockstamp__no_execution_payload__raises_assertion(self, block_details):
        block_details.message.body.execution_payload = None

        with pytest.raises(AssertionError, match="execution_payload required"):
            build_blockstamp(block_details)


@pytest.mark.unit
class TestBlockstampBuilder:
    @pytest.fixture
    def block_details(self):
        return BlockDetailsResponseFactory.build()

    @pytest.fixture
    def cc(self, block_details):
        return Mock(get_block_details=Mock(return_value=block_details))

    @pytest.fixture
    def subject(self, cc):
        return BlockstampBuilder(cc=cc, w3_eth=Mock())

    def test_build_blockstamp__with_execution_payload__returns_blockstamp(self, subject, block_details):
        bs = subject.build_blockstamp(block_details)

        execution_payload = block_details.message.body.execution_payload
        assert isinstance(bs, BlockStamp)
        assert bs.slot_number == block_details.message.slot
        assert bs.block_number == execution_payload.block_number

    def test_build_blockstamp__no_execution_payload__uses_state_latest_block_hash(self, subject, block_details):
        block_details.message.body.execution_payload = None
        el_block = {'number': 12345, 'timestamp': 99999}
        state_view = Mock(latest_block_hash='0xdeadbeef')
        subject.cc.get_state_view = Mock(return_value=state_view)
        subject.w3_eth.get_block = Mock(return_value=el_block)

        bs = subject.build_blockstamp(block_details)

        assert bs.block_number == 12345
        assert bs.slot_number == block_details.message.slot
        subject.w3_eth.get_block.assert_called_once_with('0xdeadbeef')
