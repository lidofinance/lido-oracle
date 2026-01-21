from unittest.mock import MagicMock

import pytest
from eth_typing import BlockNumber

from src.utils.block import get_block_timestamps

SECONDS_PER_SLOT = 12
BLOCKS_PER_DAY = 7200
MAX_RPC_CALLS = 500


def _timestamp_for_block(block_num: int, first_block: int, base_ts: int, missed_after: set[int]) -> int:
    """
    Calculate the timestamp for a block in a synthetic chain.

    This function simulates a blockchain where blocks are produced at regular intervals
    (SECONDS_PER_SLOT), with the ability to model "missed slots" - blocks that were
    skipped, causing a gap in the sequence.

    Args:
        block_num: The block number to calculate timestamp for
        first_block: The starting block number of the chain
        base_ts: The Unix timestamp of the first block
        missed_after: Set of block numbers after which a slot was missed

    Returns:
        The Unix timestamp for the given block number

    Example:
        If block 100 is in missed_after, then block 101 will have a timestamp
        that's 2 * SECONDS_PER_SLOT after block 100 (instead of just 1 * SECONDS_PER_SLOT).
    """
    # Model missed slots by inserting a full-slot delay after each gap boundary.
    # Count how many slots were missed before this block.
    missed = sum(1 for gap in missed_after if block_num > gap)
    return base_ts + (block_num - first_block + missed) * SECONDS_PER_SLOT


def _make_web3_mock(get_block):
    w3 = MagicMock(spec_set=["eth"])
    w3.eth = MagicMock(spec_set=["get_block"])
    w3.eth.get_block = get_block
    return w3


@pytest.mark.unit
class TestBlockTimestampsSyntheticChain:
    """Scenario tests for block timestamp fetching without RPC access."""

    def test_full_day_no_missed_slots(self):
        """
        Test optimal performance case: a full day of blocks with no missed slots.

        This test verifies that when blocks are produced at perfectly regular intervals
        with no gaps, the get_block_timestamps function can interpolate all timestamps
        by only fetching the first and last block (2 RPC calls total).

        Expected behavior:
        - All 7200 blocks (one day) should have correct timestamps
        - Only 2 RPC calls should be made (first and last block)
        - This demonstrates maximum efficiency of the binary search optimization
        """
        first_block = 10_000
        base_ts = 1_700_000_000
        missed_after: set[int] = set()  # No missed slots in this test
        blocks = {BlockNumber(b) for b in range(first_block, first_block + BLOCKS_PER_DAY)}

        def get_block(block_id):
            # Deterministic synthetic chain with no gaps.
            return {"timestamp": _timestamp_for_block(int(block_id), first_block, base_ts, missed_after)}

        mock_get_block = MagicMock(side_effect=get_block)
        w3 = _make_web3_mock(mock_get_block)

        result = get_block_timestamps(w3, blocks, SECONDS_PER_SLOT)
        # Build expected timestamps directly from the same synthetic model.
        expected = {
            BlockNumber(b): _timestamp_for_block(b, first_block, base_ts, missed_after)
            for b in range(first_block, first_block + BLOCKS_PER_DAY)
        }

        assert result == expected
        # No missed slots => only endpoints need to be fetched (optimal case).
        assert mock_get_block.call_count == 2
        # Each RPC is ~1ms; keep under 100ms budget.
        assert mock_get_block.call_count <= MAX_RPC_CALLS

    @pytest.mark.parametrize(
        "stride",
        [
            10,  # Every 10th block
            100,  # Every 100th block
            1000,  # Every 1000th block
        ],
    )
    def test_samples_with_missed_slots_match_manual(self, stride):
        """
        Test binary search optimization with sampled blocks and missed slots.

        This test simulates a realistic scenario where:
        1. We only need timestamps for a subset of blocks (sampled at regular intervals)
        2. There are missed slots in the chain (causing timestamp irregularities, randomly distributed)

        The binary search optimization should:
        - Detect the missed slots by noticing timestamp gaps
        - Only fetch additional blocks where needed to refine the search
        - Stay within the performance budget (MAX_RPC_CALLS)

        Args:
            stride: How many blocks to skip between samples (10, 100, or 1000)
        """
        first_block = 20_000
        base_ts = 1_800_000_000

        # For more realistic test coverage, simulate approximately 0.5% of slots as missed.
        # 0.5% of BLOCKS_PER_DAY (7200) is 36 slots; distribute them evenly within the range.
        missed_after = {first_block + i * (BLOCKS_PER_DAY // 36) for i in range(1, 37)}

        def get_block(block_id):
            # Synthetic chain with two missed slots to force binary search behavior.
            return {"timestamp": _timestamp_for_block(int(block_id), first_block, base_ts, missed_after)}

        sampled_blocks = list(range(first_block, first_block + BLOCKS_PER_DAY, stride))
        blocks = {BlockNumber(b) for b in sampled_blocks}

        mock_get_block = MagicMock(side_effect=get_block)
        w3 = _make_web3_mock(mock_get_block)
        result = get_block_timestamps(w3, blocks, SECONDS_PER_SLOT)

        # Expected values from the synthetic model (manual fetch equivalent).
        expected = {BlockNumber(b): _timestamp_for_block(b, first_block, base_ts, missed_after) for b in sampled_blocks}

        # Verify all timestamps are correct
        assert result == expected
        # Ensure we stay within the performance budget (each RPC is ~1ms; keep under budget)
        assert mock_get_block.call_count <= MAX_RPC_CALLS
