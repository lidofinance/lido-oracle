"""
Unit tests for block timestamp fetching with binary search optimization.

Tests the get_block_timestamps function which uses binary search to detect
missed slots and minimize RPC calls.
"""

from unittest.mock import MagicMock, patch

import pytest
from eth_typing import BlockNumber

from src.utils.block import _should_batch, get_block_timestamps

SECONDS_PER_SLOT = 12


@pytest.mark.unit
class TestGetBlockTimestampsBasicCases:
    """Basic functionality tests for get_block_timestamps."""

    def test_empty_block_set_returns_empty_dict(self, web3, monkeypatch):
        """Empty input should return empty dict without any RPC calls."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        result = get_block_timestamps(web3, set(), SECONDS_PER_SLOT)

        assert result == {}
        mock_get_block.assert_not_called()

    def test_single_block_fetches_once(self, web3, monkeypatch):
        """Single block should make exactly one RPC call."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block = MagicMock(return_value={"timestamp": 1000})
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        result = get_block_timestamps(web3, {BlockNumber(100)}, SECONDS_PER_SLOT)

        assert result == {BlockNumber(100): 1000}
        mock_get_block.assert_called_once_with(BlockNumber(100))

    def test_two_blocks_no_missed_slots(self, web3, monkeypatch):
        """Two consecutive blocks with no missed slots: 2 RPC calls."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = [
            {"timestamp": 1000},  # first block
            {"timestamp": 1012},  # last block (1000 + 12)
        ]

        result = get_block_timestamps(web3, {BlockNumber(100), BlockNumber(101)}, SECONDS_PER_SLOT)

        assert result == {BlockNumber(100): 1000, BlockNumber(101): 1012}
        assert mock_get_block.call_count == 2

    def test_two_blocks_with_missed_slot(self, web3, monkeypatch):
        """Two consecutive blocks with missed slot between them: 2 RPC calls, actual timestamps used."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        # Block 100 at 1000, block 101 at 1024 (missed one slot - should be 1012)
        mock_get_block.side_effect = [
            {"timestamp": 1000},
            {"timestamp": 1024},  # 2 slots elapsed instead of 1
        ]

        result = get_block_timestamps(web3, {BlockNumber(100), BlockNumber(101)}, SECONDS_PER_SLOT)

        # Both timestamps are actual RPC values since we can't calculate with missed slot
        assert result == {BlockNumber(100): 1000, BlockNumber(101): 1024}
        assert mock_get_block.call_count == 2

    def test_multiple_blocks_no_missed_slots_calculates_intermediate(self, web3, monkeypatch):
        """
        Multiple blocks with no missed slots: only 2 RPC calls.
        All intermediate timestamps calculated arithmetically.
        """
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = [
            {"timestamp": 1000},  # first block (100)
            {"timestamp": 1048},  # last block (104) = 1000 + 4*12
        ]

        blocks = {BlockNumber(b) for b in [100, 101, 102, 103, 104]}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        expected = {
            BlockNumber(100): 1000,
            BlockNumber(101): 1012,
            BlockNumber(102): 1024,
            BlockNumber(103): 1036,
            BlockNumber(104): 1048,
        }
        assert result == expected
        assert mock_get_block.call_count == 2

    def test_three_blocks_no_missed_slots(self, web3, monkeypatch):
        """Three blocks with no missed slots: 2 RPC calls, middle calculated."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = [
            {"timestamp": 1000},
            {"timestamp": 1024},
        ]

        blocks = {BlockNumber(100), BlockNumber(101), BlockNumber(102)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        expected = {
            BlockNumber(100): 1000,
            BlockNumber(101): 1012,
            BlockNumber(102): 1024,
        }
        assert result == expected
        assert mock_get_block.call_count == 2


@pytest.mark.unit
class TestGetBlockTimestampsMissedSlots:
    """Tests for missed slot detection and binary search behavior."""

    def test_three_blocks_missed_slot_at_start(self, web3, monkeypatch):
        """Missed slot between first and second block triggers binary search."""

        # Block 100: 1000, 101: 1024 (missed slot), 102: 1036
        def mock_get_block_func(block_num):
            timestamps = {
                BlockNumber(100): 1000,
                BlockNumber(101): 1024,  # Should be 1012 if no missed slot
                BlockNumber(102): 1036,
            }
            return {"timestamp": timestamps[block_num]}

        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = mock_get_block_func

        blocks = {BlockNumber(100), BlockNumber(101), BlockNumber(102)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        expected = {
            BlockNumber(100): 1000,
            BlockNumber(101): 1024,
            BlockNumber(102): 1036,
        }
        assert result == expected

    def test_three_blocks_missed_slot_at_end(self, web3, monkeypatch):
        """Missed slot between second and third block triggers binary search."""

        # Block 100: 1000, 101: 1012, 102: 1036 (missed slot before 102)
        def mock_get_block_func(block_num):
            timestamps = {
                BlockNumber(100): 1000,
                BlockNumber(101): 1012,
                BlockNumber(102): 1036,  # Should be 1024 if no missed slot
            }
            return {"timestamp": timestamps[block_num]}

        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = mock_get_block_func

        blocks = {BlockNumber(100), BlockNumber(101), BlockNumber(102)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        expected = {
            BlockNumber(100): 1000,
            BlockNumber(101): 1012,
            BlockNumber(102): 1036,
        }
        assert result == expected

    def test_four_blocks_missed_slot_in_middle(self, web3, monkeypatch):
        """Missed slot in the middle of range triggers binary search."""

        # Block 100: 1000, 101: 1012, 102: 1036 (missed), 103: 1048
        def mock_get_block_func(block_num):
            timestamps = {
                BlockNumber(100): 1000,
                BlockNumber(101): 1012,
                BlockNumber(102): 1036,
                BlockNumber(103): 1048,
            }
            return {"timestamp": timestamps[block_num]}

        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = mock_get_block_func

        blocks = {BlockNumber(b) for b in [100, 101, 102, 103]}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        expected = {
            BlockNumber(100): 1000,
            BlockNumber(101): 1012,
            BlockNumber(102): 1036,
            BlockNumber(103): 1048,
        }
        assert result == expected
        # Binary search needed - more than 2 RPC calls
        assert mock_get_block.call_count > 2

    def test_multiple_missed_slots_consecutive(self, web3, monkeypatch):
        """Multiple consecutive missed slots (2 slots missed together)."""

        # Block 100: 1000, 101: 1012, 102: 1048 (2 missed slots), 103: 1060
        def mock_get_block_func(block_num):
            timestamps = {
                BlockNumber(100): 1000,
                BlockNumber(101): 1012,
                BlockNumber(102): 1048,  # 3 slots elapsed (1012 + 36)
                BlockNumber(103): 1060,
            }
            return {"timestamp": timestamps[block_num]}

        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = mock_get_block_func

        blocks = {BlockNumber(b) for b in [100, 101, 102, 103]}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        expected = {
            BlockNumber(100): 1000,
            BlockNumber(101): 1012,
            BlockNumber(102): 1048,
            BlockNumber(103): 1060,
        }
        assert result == expected

    def test_multiple_missed_slots_at_different_locations(self, web3, monkeypatch):
        """Multiple missed slots at different locations in the range."""

        # Missed slot after block 101 AND after block 103
        def mock_get_block_func(block_num):
            timestamps = {
                BlockNumber(100): 1000,
                BlockNumber(101): 1012,
                BlockNumber(102): 1036,  # missed slot (should be 1024)
                BlockNumber(103): 1048,
                BlockNumber(104): 1072,  # missed slot (should be 1060)
            }
            return {"timestamp": timestamps[block_num]}

        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = mock_get_block_func

        blocks = {BlockNumber(b) for b in [100, 101, 102, 103, 104]}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        expected = {
            BlockNumber(100): 1000,
            BlockNumber(101): 1012,
            BlockNumber(102): 1036,
            BlockNumber(103): 1048,
            BlockNumber(104): 1072,
        }
        assert result == expected

    def test_worst_case_missed_slot_between_every_block(self, web3, monkeypatch):
        """Worst case: missed slot between every consecutive block pair."""

        # Every block is 24 seconds apart instead of 12
        def mock_get_block_func(block_num):
            base_ts = 1000
            offset = (block_num - 100) * 24  # 2 slots per block
            return {"timestamp": base_ts + offset}

        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = mock_get_block_func

        blocks = {BlockNumber(b) for b in [100, 101, 102, 103, 104]}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        expected = {
            BlockNumber(100): 1000,
            BlockNumber(101): 1024,
            BlockNumber(102): 1048,
            BlockNumber(103): 1072,
            BlockNumber(104): 1096,
        }
        assert result == expected
        # All blocks need to be fetched individually
        assert mock_get_block.call_count == 5


@pytest.mark.unit
class TestGetBlockTimestampsNonConsecutiveBlocks:
    """Tests for non-consecutive block numbers."""

    def test_non_consecutive_blocks_no_missed_slots(self, web3, monkeypatch):
        """
        Non-consecutive block numbers but no missed slots.
        Timestamps should be calculated correctly based on block number difference.
        """
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = [
            {"timestamp": 1000},  # block 100
            {"timestamp": 1048},  # block 104 = 1000 + 4*12
        ]

        blocks = {BlockNumber(100), BlockNumber(102), BlockNumber(104)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        expected = {
            BlockNumber(100): 1000,
            BlockNumber(102): 1024,  # 1000 + 2*12
            BlockNumber(104): 1048,  # 1000 + 4*12
        }
        assert result == expected
        assert mock_get_block.call_count == 2

    def test_sparse_blocks_large_gaps_no_missed_slots(self, web3, monkeypatch):
        """Sparse block numbers with large gaps, no missed slots."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = [
            {"timestamp": 1000},
            {"timestamp": 3400},  # block 300 = 1000 + 200*12
        ]

        blocks = {BlockNumber(100), BlockNumber(200), BlockNumber(300)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        expected = {
            BlockNumber(100): 1000,
            BlockNumber(200): 2200,  # 1000 + 100*12
            BlockNumber(300): 3400,  # 1000 + 200*12
        }
        assert result == expected
        assert mock_get_block.call_count == 2

    def test_non_consecutive_with_missed_slot(self, web3, monkeypatch):
        """Non-consecutive blocks with missed slot in the range."""

        # Blocks 100, 105, 110 with a missed slot somewhere
        def mock_get_block_func(block_num):
            timestamps = {
                BlockNumber(100): 1000,
                BlockNumber(105): 1072,  # Should be 1060 if no missed slot (100 + 5*12)
                BlockNumber(110): 1132,  # 1072 + 5*12 = correct
            }
            return {"timestamp": timestamps[block_num]}

        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = mock_get_block_func

        blocks = {BlockNumber(100), BlockNumber(105), BlockNumber(110)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        expected = {
            BlockNumber(100): 1000,
            BlockNumber(105): 1072,
            BlockNumber(110): 1132,
        }
        assert result == expected

    def test_only_first_and_last_blocks_in_range(self, web3, monkeypatch):
        """Only first and last blocks of a large range requested."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = [
            {"timestamp": 1000},
            {"timestamp": 13000},  # 1000 + 1000*12
        ]

        blocks = {BlockNumber(100), BlockNumber(1100)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        expected = {
            BlockNumber(100): 1000,
            BlockNumber(1100): 13000,
        }
        assert result == expected
        assert mock_get_block.call_count == 2


@pytest.mark.unit
class TestGetBlockTimestampsLargeRanges:
    """Tests for large block ranges."""

    def test_100_blocks_no_missed_slots(self, web3, monkeypatch):
        """100 consecutive blocks with no missed slots: only 2 RPC calls."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        first_timestamp = 10000
        first_block = 1000
        last_block = 1099
        last_timestamp = first_timestamp + (last_block - first_block) * SECONDS_PER_SLOT

        mock_get_block.side_effect = [
            {"timestamp": first_timestamp},
            {"timestamp": last_timestamp},
        ]

        blocks = {BlockNumber(b) for b in range(first_block, last_block + 1)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        assert len(result) == 100
        assert result[BlockNumber(1000)] == first_timestamp
        assert result[BlockNumber(1099)] == last_timestamp
        assert result[BlockNumber(1050)] == first_timestamp + 50 * SECONDS_PER_SLOT
        assert mock_get_block.call_count == 2

    def test_1000_blocks_no_missed_slots(self, web3, monkeypatch):
        """1000 blocks with no missed slots: only 2 RPC calls."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        first_timestamp = 100000
        first_block = 5000
        last_block = 5999
        last_timestamp = first_timestamp + (last_block - first_block) * SECONDS_PER_SLOT

        mock_get_block.side_effect = [
            {"timestamp": first_timestamp},
            {"timestamp": last_timestamp},
        ]

        blocks = {BlockNumber(b) for b in range(first_block, last_block + 1)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        assert len(result) == 1000
        assert result[BlockNumber(5000)] == first_timestamp
        assert result[BlockNumber(5999)] == last_timestamp
        assert result[BlockNumber(5500)] == first_timestamp + 500 * SECONDS_PER_SLOT
        assert mock_get_block.call_count == 2

    def test_large_range_single_missed_slot(self, web3, monkeypatch):
        """Large range with a single missed slot: requires binary search."""

        # 100 blocks, missed slot in the middle (between block 1049 and 1050)
        def mock_get_block_func(block_num):
            base_ts = 10000
            if block_num < 1050:
                # Normal timestamps before the gap
                return {"timestamp": base_ts + (block_num - 1000) * SECONDS_PER_SLOT}
            else:
                # After gap: one extra slot's worth of time
                return {"timestamp": base_ts + (block_num - 1000) * SECONDS_PER_SLOT + SECONDS_PER_SLOT}

        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = mock_get_block_func

        blocks = {BlockNumber(b) for b in range(1000, 1100)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        assert len(result) == 100
        # Before gap: calculated correctly
        assert result[BlockNumber(1000)] == 10000
        assert result[BlockNumber(1049)] == 10000 + 49 * SECONDS_PER_SLOT
        # After gap: actual timestamps
        assert result[BlockNumber(1050)] == 10000 + 51 * SECONDS_PER_SLOT
        assert result[BlockNumber(1099)] == 10000 + 100 * SECONDS_PER_SLOT


@pytest.mark.unit
class TestGetBlockTimestampsRPCCallCounting:
    """Tests to verify exact RPC call counts."""

    def test_exact_rpc_count_no_missed_slots(self, web3, monkeypatch):
        """Verify exactly 2 RPC calls when no missed slots."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = [
            {"timestamp": 1000},
            {"timestamp": 1120},  # 1000 + 10*12
        ]

        blocks = {BlockNumber(b) for b in range(100, 111)}  # 11 blocks
        get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        assert mock_get_block.call_count == 2

    def test_rpc_count_with_one_missed_slot_in_four_blocks(self, web3, monkeypatch):
        """4 blocks with one missed slot: should need at most 4 RPC calls."""

        def mock_get_block_func(block_num):
            timestamps = {
                BlockNumber(100): 1000,
                BlockNumber(101): 1012,
                BlockNumber(102): 1036,  # missed slot
                BlockNumber(103): 1048,
            }
            return {"timestamp": timestamps[block_num]}

        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = mock_get_block_func

        blocks = {BlockNumber(b) for b in [100, 101, 102, 103]}
        get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        # Binary search: first/last (2), then mid (1), then possibly more
        # Should be at most 4 for 4 blocks
        assert mock_get_block.call_count <= 4

    def test_single_block_exactly_one_rpc_call(self, web3, monkeypatch):
        """Single block needs exactly 1 RPC call."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.return_value = {"timestamp": 1000}

        get_block_timestamps(web3, {BlockNumber(100)}, SECONDS_PER_SLOT)

        assert mock_get_block.call_count == 1


@pytest.mark.unit
class TestGetBlockTimestampsCaching:
    """Tests for timestamp caching during recursion."""

    def test_caching_prevents_duplicate_fetches(self, web3, monkeypatch):
        """When binary search recurses, cached timestamps prevent refetching."""
        fetched_blocks = []

        def mock_get_block_func(block_num):
            fetched_blocks.append(block_num)
            timestamps = {
                BlockNumber(100): 1000,
                BlockNumber(101): 1012,
                BlockNumber(102): 1036,  # missed slot
                BlockNumber(103): 1048,
            }
            return {"timestamp": timestamps[block_num]}

        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = mock_get_block_func

        blocks = {BlockNumber(b) for b in [100, 101, 102, 103]}
        get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        # Each block should be fetched at most once
        for block in [100, 101, 102, 103]:
            assert fetched_blocks.count(BlockNumber(block)) <= 1, f"Block {block} was fetched more than once"

    def test_midpoint_caching_during_binary_search(self, web3, monkeypatch):
        """Midpoint blocks are cached and not refetched in subsequent recursion."""
        fetched_blocks = []

        def mock_get_block_func(block_num):
            fetched_blocks.append(block_num)
            # Missed slot between 102 and 103
            base = 1000
            if block_num <= 102:
                return {"timestamp": base + (block_num - 100) * SECONDS_PER_SLOT}
            else:
                # Extra 12 seconds after block 102
                return {"timestamp": base + (block_num - 100) * SECONDS_PER_SLOT + SECONDS_PER_SLOT}

        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = mock_get_block_func

        blocks = {BlockNumber(b) for b in range(100, 106)}  # 6 blocks
        get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        # No duplicates
        assert len(fetched_blocks) == len(set(fetched_blocks)), f"Duplicate fetches detected: {fetched_blocks}"


@pytest.mark.unit
class TestGetBlockTimestampsEdgeCases:
    """Edge case tests for get_block_timestamps."""

    def test_blocks_input_is_sorted_internally(self, web3, monkeypatch):
        """Verify that blocks are processed in sorted order regardless of input."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = [
            {"timestamp": 1000},
            {"timestamp": 1048},
        ]

        # Input blocks in random order
        blocks = {BlockNumber(104), BlockNumber(100), BlockNumber(102)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        expected = {
            BlockNumber(100): 1000,
            BlockNumber(102): 1024,
            BlockNumber(104): 1048,
        }
        assert result == expected

    def test_timestamps_are_integers(self, web3, monkeypatch):
        """Verify all returned timestamps are integers."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = [
            {"timestamp": 1000},
            {"timestamp": 1024},
        ]

        blocks = {BlockNumber(100), BlockNumber(101), BlockNumber(102)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        assert all(isinstance(ts, int) for ts in result.values())

    def test_large_block_numbers(self, web3, monkeypatch):
        """Test with realistically large block numbers (mainnet scale)."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        # Current mainnet block numbers are ~20 million
        first_block = BlockNumber(20_000_000)
        last_block = BlockNumber(20_000_100)
        first_timestamp = 1700000000  # Realistic timestamp

        mock_get_block.side_effect = [
            {"timestamp": first_timestamp},
            {"timestamp": first_timestamp + 100 * SECONDS_PER_SLOT},
        ]

        blocks = {BlockNumber(b) for b in range(first_block, last_block + 1)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        assert len(result) == 101
        assert result[first_block] == first_timestamp
        assert result[last_block] == first_timestamp + 100 * SECONDS_PER_SLOT
        assert mock_get_block.call_count == 2

    def test_large_timestamps(self, web3, monkeypatch):
        """Test with realistically large timestamps."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        # Unix timestamp for 2024 is around 1.7 billion
        base_timestamp = 1700000000

        mock_get_block.side_effect = [
            {"timestamp": base_timestamp},
            {"timestamp": base_timestamp + 48},
        ]

        blocks = {BlockNumber(100), BlockNumber(101), BlockNumber(102), BlockNumber(103), BlockNumber(104)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        assert result[BlockNumber(100)] == base_timestamp
        assert result[BlockNumber(102)] == base_timestamp + 24
        assert result[BlockNumber(104)] == base_timestamp + 48

    def test_set_deduplication(self, web3, monkeypatch):
        """Sets automatically deduplicate, but verify single block behavior."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.return_value = {"timestamp": 1000}

        result = get_block_timestamps(web3, {BlockNumber(100)}, SECONDS_PER_SLOT)

        assert result == {BlockNumber(100): 1000}
        mock_get_block.assert_called_once()

    def test_result_contains_all_requested_blocks(self, web3, monkeypatch):
        """Verify result dict contains exactly the requested blocks."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = [
            {"timestamp": 1000},
            {"timestamp": 1048},
        ]

        requested = {BlockNumber(100), BlockNumber(102), BlockNumber(104)}
        result = get_block_timestamps(web3, requested, SECONDS_PER_SLOT)

        assert set(result.keys()) == requested


@pytest.mark.unit
class TestGetBlockTimestampsDifferentSlotTimes:
    """Tests with different seconds_per_slot values."""

    def test_6_second_slot_time(self, web3, monkeypatch):
        """Test with 6 second slot time (hypothetical)."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        seconds_per_slot = 6

        mock_get_block.side_effect = [
            {"timestamp": 1000},
            {"timestamp": 1024},  # 1000 + 4*6 = 1024
        ]

        blocks = {BlockNumber(100), BlockNumber(102), BlockNumber(104)}
        result = get_block_timestamps(web3, blocks, seconds_per_slot)

        expected = {
            BlockNumber(100): 1000,
            BlockNumber(102): 1012,  # 1000 + 2*6
            BlockNumber(104): 1024,  # 1000 + 4*6
        }
        assert result == expected

    def test_1_second_slot_time(self, web3, monkeypatch):
        """Test with 1 second slot time (edge case)."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        seconds_per_slot = 1

        mock_get_block.side_effect = [
            {"timestamp": 1000},
            {"timestamp": 1004},  # 1000 + 4*1
        ]

        blocks = {BlockNumber(100), BlockNumber(102), BlockNumber(104)}
        result = get_block_timestamps(web3, blocks, seconds_per_slot)

        expected = {
            BlockNumber(100): 1000,
            BlockNumber(102): 1002,
            BlockNumber(104): 1004,
        }
        assert result == expected

    def test_24_second_slot_time(self, web3, monkeypatch):
        """Test with 24 second slot time."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        seconds_per_slot = 24

        mock_get_block.side_effect = [
            {"timestamp": 1000},
            {"timestamp": 1096},  # 1000 + 4*24
        ]

        blocks = {BlockNumber(100), BlockNumber(102), BlockNumber(104)}
        result = get_block_timestamps(web3, blocks, seconds_per_slot)

        expected = {
            BlockNumber(100): 1000,
            BlockNumber(102): 1048,  # 1000 + 2*24
            BlockNumber(104): 1096,  # 1000 + 4*24
        }
        assert result == expected


@pytest.mark.unit
class TestGetBlockTimestampsBinarySearchBehavior:
    """Tests specifically for binary search algorithm behavior."""

    def test_binary_search_splits_correctly(self, web3, monkeypatch):
        """Verify binary search splits range at midpoint."""
        call_order = []

        def mock_get_block_func(block_num):
            call_order.append(block_num)
            # Missed slot between 102 and 103
            timestamps = {
                BlockNumber(100): 1000,
                BlockNumber(101): 1012,
                BlockNumber(102): 1024,
                BlockNumber(103): 1048,  # Should be 1036
                BlockNumber(104): 1060,
            }
            return {"timestamp": timestamps[block_num]}

        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = mock_get_block_func

        blocks = {BlockNumber(b) for b in [100, 101, 102, 103, 104]}
        get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        # First call should be first block (100)
        assert call_order[0] == BlockNumber(100)
        # Second call should be last block (104)
        assert call_order[1] == BlockNumber(104)
        # Third call (binary search midpoint) should be 102
        assert BlockNumber(102) in call_order

    def test_recursive_subdivision_with_multiple_gaps(self, web3, monkeypatch):
        """Test that algorithm correctly handles multiple subdivisions."""

        # 8 blocks with gaps at different positions
        def mock_get_block_func(block_num):
            timestamps = {
                BlockNumber(100): 1000,
                BlockNumber(101): 1012,
                BlockNumber(102): 1036,  # gap
                BlockNumber(103): 1048,
                BlockNumber(104): 1060,
                BlockNumber(105): 1084,  # gap
                BlockNumber(106): 1096,
                BlockNumber(107): 1108,
            }
            return {"timestamp": timestamps[block_num]}

        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = mock_get_block_func

        blocks = {BlockNumber(b) for b in range(100, 108)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        # All timestamps should be correct
        assert result[BlockNumber(100)] == 1000
        assert result[BlockNumber(102)] == 1036
        assert result[BlockNumber(105)] == 1084
        assert result[BlockNumber(107)] == 1108

    def test_optimal_rpc_calls_for_single_gap(self, web3, monkeypatch):
        """Binary search should find single gap efficiently."""
        call_count = {"count": 0}

        def mock_get_block_func(block_num):
            call_count["count"] += 1
            # Gap between block 107 and 108 in a 16-block range
            base = 1000
            if block_num < 108:
                return {"timestamp": base + (block_num - 100) * SECONDS_PER_SLOT}
            else:
                return {"timestamp": base + (block_num - 100) * SECONDS_PER_SLOT + SECONDS_PER_SLOT}

        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = mock_get_block_func

        blocks = {BlockNumber(b) for b in range(100, 116)}  # 16 blocks
        get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        # Binary search for one gap in 16 elements: O(log 16) = 4 depth
        # Should be much less than 16 (naive approach)
        assert call_count["count"] < 16


@pytest.mark.unit
class TestGetBlockTimestampsIntegrationScenarios:
    """Tests simulating real-world usage scenarios."""

    def test_typical_oracle_report_blocks(self, web3, monkeypatch):
        """Simulate typical oracle report with ~225 blocks per frame."""
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        # 225 blocks (one frame at 32 slots/epoch, ~7 epochs)
        first_block = 20_000_000
        num_blocks = 225
        first_timestamp = 1700000000

        mock_get_block.side_effect = [
            {"timestamp": first_timestamp},
            {"timestamp": first_timestamp + (num_blocks - 1) * SECONDS_PER_SLOT},
        ]

        blocks = {BlockNumber(b) for b in range(first_block, first_block + num_blocks)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        assert len(result) == num_blocks
        assert mock_get_block.call_count == 2  # Optimal case

    def test_sparse_event_blocks(self, web3, monkeypatch):
        """Simulate sparse blocks from event logs."""
        # Events at blocks 100, 150, 200, 250, 300
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = [
            {"timestamp": 1000},
            {"timestamp": 3400},  # 1000 + 200*12
        ]

        blocks = {BlockNumber(100), BlockNumber(150), BlockNumber(200), BlockNumber(250), BlockNumber(300)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        expected = {
            BlockNumber(100): 1000,
            BlockNumber(150): 1600,  # 1000 + 50*12
            BlockNumber(200): 2200,  # 1000 + 100*12
            BlockNumber(250): 2800,  # 1000 + 150*12
            BlockNumber(300): 3400,  # 1000 + 200*12
        }
        assert result == expected
        assert mock_get_block.call_count == 2

    def test_blocks_around_known_missed_slot_event(self, web3, monkeypatch):
        """Simulate fetching blocks around a known missed slot."""

        # Simulating a real scenario where a proposer missed their slot
        def mock_get_block_func(block_num):
            base = 1700000000
            # Normal progression until block 105, then one missed slot
            if block_num <= 105:
                return {"timestamp": base + (block_num - 100) * SECONDS_PER_SLOT}
            else:
                # After missed slot: extra 12 seconds
                return {"timestamp": base + (block_num - 100) * SECONDS_PER_SLOT + SECONDS_PER_SLOT}

        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = mock_get_block_func

        blocks = {BlockNumber(b) for b in range(100, 111)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        # Verify the gap is reflected correctly
        assert result[BlockNumber(105)] == 1700000000 + 5 * SECONDS_PER_SLOT
        assert result[BlockNumber(106)] == 1700000000 + 7 * SECONDS_PER_SLOT  # 6 + 1 extra


@pytest.mark.unit
class TestGetBlockTimestampsVsNaiveApproach:
    """Tests comparing optimized algorithm vs naive individual fetches."""

    def test_7200_blocks_no_missed_slots_vs_naive(self, web3, monkeypatch):
        """
        Compare optimized algorithm vs naive approach for 7200 blocks (full day).

        Naive approach: 7200 RPC calls (one per block)
        Optimized (no missed slots): 2 RPC calls

        This demonstrates 3600x reduction in RPC calls.
        """
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        num_blocks = 7200
        first_block = 20_000_000
        first_timestamp = 1700000000
        last_timestamp = first_timestamp + (num_blocks - 1) * SECONDS_PER_SLOT

        mock_get_block.side_effect = [
            {"timestamp": first_timestamp},
            {"timestamp": last_timestamp},
        ]

        blocks = {BlockNumber(b) for b in range(first_block, first_block + num_blocks)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        # Verify all 7200 blocks have timestamps
        assert len(result) == num_blocks

        # Verify correctness of calculated timestamps
        assert result[BlockNumber(first_block)] == first_timestamp
        assert result[BlockNumber(first_block + num_blocks - 1)] == last_timestamp
        # Check middle block
        mid_block = first_block + num_blocks // 2
        assert result[BlockNumber(mid_block)] == first_timestamp + (num_blocks // 2) * SECONDS_PER_SLOT
        # Check random sample blocks
        assert result[BlockNumber(first_block + 100)] == first_timestamp + 100 * SECONDS_PER_SLOT
        assert result[BlockNumber(first_block + 1000)] == first_timestamp + 1000 * SECONDS_PER_SLOT
        assert result[BlockNumber(first_block + 5000)] == first_timestamp + 5000 * SECONDS_PER_SLOT

        # KEY ASSERTION: Only 2 RPC calls vs 7200 naive calls
        optimized_calls = mock_get_block.call_count
        naive_calls = num_blocks

        assert optimized_calls == 2
        assert naive_calls / optimized_calls == 3600  # 3600x improvement

    def test_7200_blocks_with_single_missed_slot_vs_naive(self, web3, monkeypatch):
        """
        7200 blocks with one missed slot still much better than naive.

        Even with binary search overhead, should be O(log n) ~ 13 calls max.
        """
        num_blocks = 7200
        first_block = 20_000_000
        first_timestamp = 1700000000
        # Missed slot at block 3600 (middle)
        gap_block = first_block + 3600

        def mock_get_block_func(block_num):
            if block_num < gap_block:
                return {"timestamp": first_timestamp + (block_num - first_block) * SECONDS_PER_SLOT}
            else:
                # After gap: extra 12 seconds
                return {"timestamp": first_timestamp + (block_num - first_block) * SECONDS_PER_SLOT + SECONDS_PER_SLOT}

        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = mock_get_block_func

        blocks = {BlockNumber(b) for b in range(first_block, first_block + num_blocks)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        assert len(result) == num_blocks

        # Verify timestamps around the gap
        assert result[BlockNumber(gap_block - 1)] == first_timestamp + 3599 * SECONDS_PER_SLOT
        assert result[BlockNumber(gap_block)] == first_timestamp + 3601 * SECONDS_PER_SLOT  # +1 slot

        # Even with binary search, should be far less than 7200
        # Binary search depth for 7200: log2(7200) ≈ 13
        # With some overhead, expect < 30 calls
        optimized_calls = mock_get_block.call_count
        naive_calls = num_blocks

        assert optimized_calls < 30, f"Expected < 30 RPC calls, got {optimized_calls}"
        assert (
            optimized_calls < naive_calls / 100
        ), f"Expected at least 100x improvement, got {naive_calls / optimized_calls:.1f}x"

    def test_7200_blocks_with_multiple_missed_slots_vs_naive(self, web3, monkeypatch):
        """
        7200 blocks with ~10 missed slots distributed throughout.

        Still significantly better than naive approach.
        """
        num_blocks = 7200
        first_block = 20_000_000
        first_timestamp = 1700000000
        # Missed slots at regular intervals (every ~720 blocks)
        gap_positions = [720, 1440, 2160, 2880, 3600, 4320, 5040, 5760, 6480]

        def mock_get_block_func(block_num):
            # Count how many gaps are before this block
            gaps_before = sum(1 for gap in gap_positions if first_block + gap <= block_num)
            return {
                "timestamp": first_timestamp
                + (block_num - first_block) * SECONDS_PER_SLOT
                + gaps_before * SECONDS_PER_SLOT
            }

        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        mock_get_block.side_effect = mock_get_block_func

        blocks = {BlockNumber(b) for b in range(first_block, first_block + num_blocks)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        assert len(result) == num_blocks

        # Even with multiple gaps, should be much less than 7200
        optimized_calls = mock_get_block.call_count
        naive_calls = num_blocks

        # With ~10 gaps, binary search needs to find each one
        # Expect < 150 calls (generous upper bound)
        assert optimized_calls < 150, f"Expected < 150 RPC calls, got {optimized_calls}"
        assert (
            optimized_calls < naive_calls / 40
        ), f"Expected at least 40x improvement, got {naive_calls / optimized_calls:.1f}x"

    def test_timestamps_correctness_for_all_7200_blocks(self, web3, monkeypatch):
        """
        Verify that ALL 7200 timestamps are calculated correctly.

        This is the correctness guarantee test.
        """
        mock_get_block = MagicMock()
        monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

        num_blocks = 7200
        first_block = 20_000_000
        first_timestamp = 1700000000
        last_timestamp = first_timestamp + (num_blocks - 1) * SECONDS_PER_SLOT

        mock_get_block.side_effect = [
            {"timestamp": first_timestamp},
            {"timestamp": last_timestamp},
        ]

        blocks = {BlockNumber(b) for b in range(first_block, first_block + num_blocks)}
        result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        # Verify EVERY single timestamp is correct
        for i in range(num_blocks):
            block_num = BlockNumber(first_block + i)
            expected_ts = first_timestamp + i * SECONDS_PER_SLOT
            assert (
                result[block_num] == expected_ts
            ), f"Block {block_num}: expected {expected_ts}, got {result[block_num]}"


@pytest.mark.unit
class TestBatchingConfiguration:
    """Tests for batching configuration and the _should_batch helper."""

    def test_should_batch_helper_function(self):
        """Test _should_batch with various BLOCK_BATCH_SIZE_LIMIT and count values."""
        with patch('src.utils.block.BLOCK_BATCH_SIZE_LIMIT', 1):
            assert _should_batch(1) is False  # limit=1, count=1
            assert _should_batch(2) is False  # limit=1, count=2
            assert _should_batch(10) is False  # limit=1, count=10

        with patch('src.utils.block.BLOCK_BATCH_SIZE_LIMIT', 10):
            assert _should_batch(1) is False  # count=1, no benefit
            assert _should_batch(2) is True  # count=2, batching enabled
            assert _should_batch(10) is True  # count=10, batching enabled

    def test_batching_disabled_when_limit_is_one(self, web3, monkeypatch):
        """When BLOCK_BATCH_SIZE_LIMIT=1, batching should be completely disabled."""
        with patch('src.utils.block.BLOCK_BATCH_SIZE_LIMIT', 1):
            mock_get_block = MagicMock()
            monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

            # Test with two blocks (endpoints)
            mock_get_block.side_effect = [
                {"timestamp": 1000},  # first block
                {"timestamp": 1012},  # last block
            ]

            result = get_block_timestamps(web3, {BlockNumber(100), BlockNumber(101)}, SECONDS_PER_SLOT)

            assert result == {BlockNumber(100): 1000, BlockNumber(101): 1012}
            # Should make 2 sequential calls, not use batching
            assert mock_get_block.call_count == 2

    def test_batching_disabled_with_multiple_blocks_no_missed_slots(self, web3, monkeypatch):
        """With BLOCK_BATCH_SIZE_LIMIT=1 and no missed slots, should still calculate correctly."""
        with patch('src.utils.block.BLOCK_BATCH_SIZE_LIMIT', 1):
            mock_get_block = MagicMock()
            monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

            mock_get_block.side_effect = [
                {"timestamp": 1000},  # first block (100)
                {"timestamp": 1048},  # last block (104)
            ]

            blocks = {BlockNumber(b) for b in [100, 101, 102, 103, 104]}
            result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

            # Timestamps should be calculated correctly
            expected = {
                BlockNumber(100): 1000,
                BlockNumber(101): 1012,
                BlockNumber(102): 1024,
                BlockNumber(103): 1036,
                BlockNumber(104): 1048,
            }
            assert result == expected
            # Only endpoints fetched (no batching)
            assert mock_get_block.call_count == 2

    def test_batching_disabled_with_missed_slots(self, web3, monkeypatch):
        """With BLOCK_BATCH_SIZE_LIMIT=1 and missed slots, should use sequential requests."""
        with patch('src.utils.block.BLOCK_BATCH_SIZE_LIMIT', 1):
            mock_get_block = MagicMock()
            monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)

            # Setup: 4 blocks with 1 missed slot
            # With BLOCK_BATCH_SIZE_LIMIT=1, binary search will be used
            # Call order: endpoints (100, 103), then midpoint (102), then remaining (101)
            mock_get_block.side_effect = [
                {"timestamp": 1000},  # block 100 (endpoint)
                {"timestamp": 1048},  # block 103 (endpoint)
                {"timestamp": 1036},  # block 102 (midpoint in binary search)
                {"timestamp": 1012},  # block 101 (remaining intermediate)
            ]

            blocks = {BlockNumber(b) for b in [100, 101, 102, 103]}
            result = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

            # Should fetch all 4 blocks sequentially (no batching)
            assert mock_get_block.call_count == 4
            assert result == {
                BlockNumber(100): 1000,
                BlockNumber(101): 1012,
                BlockNumber(102): 1036,
                BlockNumber(103): 1048,
            }

    def test_timestamps_match_regardless_of_batching_config(self, web3, monkeypatch):
        """Timestamps should be identical with BLOCK_BATCH_SIZE_LIMIT=1 and =10."""
        blocks = {BlockNumber(b) for b in range(100, 110)}
        first_ts = 1000
        last_ts = 1108  # 1000 + 9*12

        def mock_get_block_func(block_num):
            return {"timestamp": first_ts + (block_num - 100) * SECONDS_PER_SLOT}

        # Test with BLOCK_BATCH_SIZE_LIMIT=1
        with patch('src.utils.block.BLOCK_BATCH_SIZE_LIMIT', 1):
            mock_get_block = MagicMock(side_effect=mock_get_block_func)
            monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)
            result_no_batch = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        # Test with BLOCK_BATCH_SIZE_LIMIT=10
        with patch('src.utils.block.BLOCK_BATCH_SIZE_LIMIT', 10):
            mock_get_block = MagicMock(side_effect=mock_get_block_func)
            monkeypatch.setattr(web3.eth, 'get_block', mock_get_block)
            result_with_batch = get_block_timestamps(web3, blocks, SECONDS_PER_SLOT)

        # Both should return identical timestamps
        assert result_no_batch == result_with_batch
        expected = {BlockNumber(100 + i): 1000 + i * 12 for i in range(10)}
        assert result_no_batch == expected
