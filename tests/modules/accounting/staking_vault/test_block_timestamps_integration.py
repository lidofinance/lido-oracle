"""
Unit tests for block timestamp fetching with binary search optimization.

These tests replace the old integration tests by using a deterministic
synthetic chain and a mocked Web3 interface.
"""

from unittest.mock import MagicMock

import pytest
from eth_typing import BlockNumber

from src.utils.block import get_block_timestamps

SECONDS_PER_SLOT = 12
BLOCKS_PER_DAY = 7200
MAX_RPC_CALLS = 50


def _timestamp_for_block(block_num: int, first_block: int, base_ts: int, missed_after: set[int]) -> int:
    # Model missed slots by inserting a full-slot delay after each gap boundary.
    missed = sum(1 for gap in missed_after if block_num > gap)
    return base_ts + (block_num - first_block + missed) * SECONDS_PER_SLOT


def _make_web3(get_block):
    # Mocked Web3 with only eth.get_block; forces batch fallback.
    w3 = MagicMock(spec_set=["eth"])
    w3.eth = MagicMock(spec_set=["get_block"])
    w3.eth.get_block = get_block
    return w3


@pytest.mark.unit
class TestBlockTimestampsSyntheticChain:
    """Scenario tests for block timestamp fetching without RPC access."""

    def test_full_day_no_missed_slots(self):
        first_block = 10_000
        base_ts = 1_700_000_000
        missed_after: set[int] = set()
        blocks = {BlockNumber(b) for b in range(first_block, first_block + BLOCKS_PER_DAY)}

        def get_block(block_id):
            # Deterministic synthetic chain with no gaps.
            return {"timestamp": _timestamp_for_block(int(block_id), first_block, base_ts, missed_after)}

        mock_get_block = MagicMock(side_effect=get_block)
        w3 = _make_web3(mock_get_block)

        result = get_block_timestamps(w3, blocks, SECONDS_PER_SLOT)
        # Build expected timestamps directly from the same synthetic model.
        expected = {
            BlockNumber(b): _timestamp_for_block(b, first_block, base_ts, missed_after)
            for b in range(first_block, first_block + BLOCKS_PER_DAY)
        }

        assert result == expected
        # No missed slots => only endpoints need to be fetched.
        assert mock_get_block.call_count == 2
        # Each RPC is ~1ms; keep under 100ms budget.
        assert mock_get_block.call_count <= MAX_RPC_CALLS

    @pytest.mark.parametrize(
        ("stride", "expected_size"),
        [
            (10, 720),
            (100, 72),
        ],
    )
    def test_samples_with_missed_slots_match_manual(self, stride, expected_size):
        first_block = 20_000
        base_ts = 1_800_000_000
        missed_after = {first_block + 1500, first_block + 4300}
        sampled_blocks = list(range(first_block, first_block + BLOCKS_PER_DAY, stride))
        blocks = {BlockNumber(b) for b in sampled_blocks}

        def get_block(block_id):
            # Synthetic chain with two missed slots to force binary search behavior.
            return {"timestamp": _timestamp_for_block(int(block_id), first_block, base_ts, missed_after)}

        mock_get_block = MagicMock(side_effect=get_block)
        w3 = _make_web3(mock_get_block)

        result = get_block_timestamps(w3, blocks, SECONDS_PER_SLOT)
        # Expected values from the synthetic model (manual fetch equivalent).
        expected = {BlockNumber(b): _timestamp_for_block(b, first_block, base_ts, missed_after) for b in sampled_blocks}

        assert len(blocks) == expected_size
        assert result == expected
        # Must fetch fewer blocks than full sample while still respecting budget.
        assert mock_get_block.call_count < len(blocks)
        # Each RPC is ~1ms; keep under 100ms budget.
        assert mock_get_block.call_count <= MAX_RPC_CALLS
