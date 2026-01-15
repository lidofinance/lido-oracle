"""
Integration tests for block timestamp fetching with binary search optimization.

These tests fetch actual blocks from Ethereum mainnet to verify that:
1. The binary search algorithm correctly calculates timestamps
2. ALL timestamps match actual block timestamps
3. RPC calls are minimized

Run with: pytest tests/modules/accounting/staking_vault/test_block_timestamps_integration.py -v -s
"""

from unittest.mock import patch

import pytest
from eth_typing import BlockNumber
from web3 import Web3

from src.utils.block import get_block_timestamps

# Ethereum mainnet seconds per slot (post-merge)
SECONDS_PER_SLOT = 12


@pytest.mark.integration
@pytest.mark.skip("This is a long running development test, not for regular CI runs.")
class TestLast24Hours:
    """Comprehensive test for last 24 hours of blocks."""

    @pytest.fixture
    def w3(self):
        """Connect to Ethereum mainnet."""
        rpc_url = "https://eth.drpc.org"
        w3 = Web3(Web3.HTTPProvider(rpc_url))

        if not w3.is_connected():
            pytest.skip(f"Skipping integration test: Could not connect to {rpc_url}")

        return w3

    def test_last_24_hours_all_timestamps_correct(self, w3):
        """
        Comprehensive test: fetch all blocks from the last 24 hours,
        verify ALL timestamps are correct, count RPC calls, and compare timing.

        ~7200 blocks per day (12 second block time).
        """
        import time

        latest_block = w3.eth.get_block("latest")
        current_block_number = latest_block["number"]

        # Last 24 hours: ~7200 blocks
        blocks_per_day = 7200
        start_block = current_block_number - blocks_per_day
        blocks = set(BlockNumber(bn) for bn in range(start_block, current_block_number))

        print(f"\n{'='*60}")
        print(f"Testing last 24 hours: {len(blocks)} blocks")
        print(f"Block range: {start_block} to {current_block_number}")
        print(f"{'='*60}")

        # Count RPC calls during timestamp fetching
        original_get_block = w3.eth.get_block
        rpc_call_count = {"count": 0}
        last_print_count = {"count": 0}

        def counting_get_block(block_id):
            rpc_call_count["count"] += 1
            # Print progress every 10 RPC calls
            if rpc_call_count["count"] - last_print_count["count"] >= 10:
                print(f"   RPC calls: {rpc_call_count['count']}...")
                last_print_count["count"] = rpc_call_count["count"]
            return original_get_block(block_id)

        # Fetch timestamps with RPC counting and timing
        print(f"\n1. Running optimized algorithm...")
        with patch.object(w3.eth, "get_block", counting_get_block):
            algo_start = time.time()
            timestamps = get_block_timestamps(w3, blocks, SECONDS_PER_SLOT)
            algo_time = time.time() - algo_start

        print(f"   Done! Time: {algo_time:.2f}s, RPC calls: {rpc_call_count['count']}")

        # Verify all blocks have timestamps
        assert len(timestamps) == len(blocks), f"Missing timestamps: expected {len(blocks)}, got {len(timestamps)}"

        # Fetch all blocks manually (batches of 500) for comparison
        print(f"\n2. Running manual fetch (batches of 500) for comparison...")
        sorted_blocks = sorted(blocks)
        batch_size = 500
        manual_timestamps = {}

        manual_start = time.time()
        for batch_start in range(0, len(sorted_blocks), batch_size):
            batch_end = min(batch_start + batch_size, len(sorted_blocks))
            batch = sorted_blocks[batch_start:batch_end]

            for block_number in batch:
                block_data = w3.eth.get_block(block_number)
                manual_timestamps[block_number] = block_data["timestamp"]

            elapsed = time.time() - manual_start
            print(f"   Fetched {batch_end}/{len(blocks)} blocks... ({elapsed:.1f}s elapsed)")

        manual_time = time.time() - manual_start
        print(f"   Done! Time: {manual_time:.2f}s, RPC calls: {len(blocks)}")

        # Compare timestamps
        print(f"\n3. Verifying all timestamps match...")
        mismatches = []

        for i, block_number in enumerate(sorted_blocks):
            calculated_timestamp = timestamps[block_number]
            actual_timestamp = manual_timestamps[block_number]

            if calculated_timestamp != actual_timestamp:
                mismatches.append(
                    {
                        "block": block_number,
                        "calculated": calculated_timestamp,
                        "actual": actual_timestamp,
                        "diff": calculated_timestamp - actual_timestamp,
                    }
                )

            if (i + 1) % 1000 == 0:
                print(f"   Verified {i + 1}/{len(blocks)} blocks...")

        print(f"   Done! Verified {len(blocks)} blocks.")

        print(f"\n{'='*60}")
        print(f"RESULTS:")
        print(f"  Total blocks: {len(blocks)}")
        print(f"{'='*60}")
        print(f"  OPTIMIZED ALGORITHM:")
        print(f"    Time: {algo_time:.2f}s")
        print(f"    RPC calls: {rpc_call_count['count']}")
        print(f"{'='*60}")
        print(f"  MANUAL FETCH (batches of 500):")
        print(f"    Time: {manual_time:.2f}s")
        print(f"    RPC calls: {len(blocks)}")
        print(f"{'='*60}")
        print(f"  IMPROVEMENT:")
        print(f"    Time: {manual_time / algo_time:.1f}x faster")
        print(f"    RPC calls: {len(blocks) / rpc_call_count['count']:.1f}x fewer")
        print(f"{'='*60}")
        print(f"  Correct timestamps: {len(blocks) - len(mismatches)}/{len(blocks)}")
        print(f"  Mismatches: {len(mismatches)}")

        if mismatches:
            print(f"\nMismatched blocks:")
            for m in mismatches[:10]:  # Show first 10
                print(f"  Block {m['block']}: calculated={m['calculated']}, actual={m['actual']}, diff={m['diff']}s")
            if len(mismatches) > 10:
                print(f"  ... and {len(mismatches) - 10} more")

        print(f"{'='*60}")

        assert len(mismatches) == 0, f"Found {len(mismatches)} blocks with incorrect timestamps"

    def test_random_720_blocks_from_last_24_hours(self, w3):
        """
        Quick test: randomly select 720 blocks from last 24 hours (~10% sample),
        verify ALL timestamps are correct, count RPC calls, and compare timing.
        """
        import random
        import time

        latest_block = w3.eth.get_block("latest")
        current_block_number = latest_block["number"]

        # Randomly select 720 blocks from last 24 hours (7200 blocks)
        blocks_per_day = 7200
        sample_size = 720
        start_block = current_block_number - blocks_per_day
        blocks = set(BlockNumber(bn) for bn in random.sample(range(start_block, current_block_number), sample_size))

        print(f"\n{'='*60}")
        print(f"Testing {len(blocks)} random blocks from last 24 hours")
        print(f"Block range: {start_block} to {current_block_number}")
        print(f"Sample: {sample_size}/{blocks_per_day} ({100*sample_size/blocks_per_day:.0f}%)")
        print(f"{'='*60}")

        # Count RPC calls during timestamp fetching
        original_get_block = w3.eth.get_block
        rpc_call_count = {"count": 0}

        def counting_get_block(block_id):
            rpc_call_count["count"] += 1
            if rpc_call_count["count"] % 10 == 0:
                print(f"   RPC calls: {rpc_call_count['count']}...")
            return original_get_block(block_id)

        # Fetch timestamps with RPC counting and timing
        print(f"\n1. Running optimized algorithm...")
        with patch.object(w3.eth, "get_block", counting_get_block):
            algo_start = time.time()
            timestamps = get_block_timestamps(w3, blocks, SECONDS_PER_SLOT)
            algo_time = time.time() - algo_start

        print(f"   Done! Time: {algo_time:.2f}s, RPC calls: {rpc_call_count['count']}")

        # Verify all blocks have timestamps
        assert len(timestamps) == len(blocks), f"Missing timestamps: expected {len(blocks)}, got {len(timestamps)}"

        # Fetch all blocks manually (batches of 100) for comparison
        print(f"\n2. Running manual fetch (batches of 100) for comparison...")
        sorted_blocks = sorted(blocks)
        batch_size = 100
        manual_timestamps = {}

        manual_start = time.time()
        for batch_start in range(0, len(sorted_blocks), batch_size):
            batch_end = min(batch_start + batch_size, len(sorted_blocks))
            batch = sorted_blocks[batch_start:batch_end]

            for block_number in batch:
                block_data = w3.eth.get_block(block_number)
                manual_timestamps[block_number] = block_data["timestamp"]

            elapsed = time.time() - manual_start
            print(f"   Fetched {batch_end}/{len(blocks)} blocks... ({elapsed:.1f}s elapsed)")

        manual_time = time.time() - manual_start
        print(f"   Done! Time: {manual_time:.2f}s, RPC calls: {len(blocks)}")

        # Compare timestamps - show sample of comparisons
        print(f"\n3. Verifying all timestamps match (calculated vs actual RPC)...")
        mismatches = []
        sample_to_show = sorted_blocks[:5]  # Show first 5 comparisons

        for i, block_number in enumerate(sorted_blocks):
            calculated_timestamp = timestamps[block_number]
            actual_timestamp = manual_timestamps[block_number]

            # Show first few comparisons as proof
            if block_number in sample_to_show:
                status = "OK" if calculated_timestamp == actual_timestamp else "MISMATCH"
                print(
                    f"   Block {block_number}: calculated={calculated_timestamp}, actual={actual_timestamp} [{status}]"
                )

            if calculated_timestamp != actual_timestamp:
                mismatches.append(
                    {
                        "block": block_number,
                        "calculated": calculated_timestamp,
                        "actual": actual_timestamp,
                        "diff": calculated_timestamp - actual_timestamp,
                    }
                )

        print(f"   ... ({len(blocks) - len(sample_to_show)} more blocks verified)")
        print(f"   Done! Verified {len(blocks)} blocks.")

        print(f"\n{'='*60}")
        print(f"RESULTS:")
        print(f"  Total blocks: {len(blocks)}")
        print(f"{'='*60}")
        print(f"  OPTIMIZED ALGORITHM:")
        print(f"    Time: {algo_time:.2f}s")
        print(f"    RPC calls: {rpc_call_count['count']}")
        print(f"{'='*60}")
        print(f"  MANUAL FETCH (batches of 100):")
        print(f"    Time: {manual_time:.2f}s")
        print(f"    RPC calls: {len(blocks)}")
        print(f"{'='*60}")
        print(f"  IMPROVEMENT:")
        print(f"    Time: {manual_time / algo_time:.1f}x faster")
        print(f"    RPC calls: {len(blocks) / rpc_call_count['count']:.1f}x fewer")
        print(f"{'='*60}")
        print(f"  Correct timestamps: {len(blocks) - len(mismatches)}/{len(blocks)}")
        print(f"  Mismatches: {len(mismatches)}")

        if mismatches:
            print(f"\nMismatched blocks:")
            for m in mismatches[:10]:
                print(f"  Block {m['block']}: calculated={m['calculated']}, actual={m['actual']}, diff={m['diff']}s")
            if len(mismatches) > 10:
                print(f"  ... and {len(mismatches) - 10} more")

        print(f"{'='*60}")

        assert len(mismatches) == 0, f"Found {len(mismatches)} blocks with incorrect timestamps"

    def test_random_72_blocks_from_last_24_hours(self, w3):
        """
        Quick test: randomly select 72 blocks from last 24 hours (~1% sample),
        verify ALL timestamps are correct, count RPC calls, and compare timing.
        """
        import random
        import time

        latest_block = w3.eth.get_block("latest")
        current_block_number = latest_block["number"]

        # Randomly select 72 blocks from last 24 hours (7200 blocks)
        blocks_per_day = 7200
        sample_size = 72
        start_block = current_block_number - blocks_per_day
        blocks = set(BlockNumber(bn) for bn in random.sample(range(start_block, current_block_number), sample_size))

        print(f"\n{'='*60}")
        print(f"Testing {len(blocks)} random blocks from last 24 hours")
        print(f"Block range: {start_block} to {current_block_number}")
        print(f"Sample: {sample_size}/{blocks_per_day} ({100*sample_size/blocks_per_day:.0f}%)")
        print(f"{'='*60}")

        # Count RPC calls during timestamp fetching
        original_get_block = w3.eth.get_block
        rpc_call_count = {"count": 0}

        def counting_get_block(block_id):
            rpc_call_count["count"] += 1
            if rpc_call_count["count"] % 10 == 0:
                print(f"   RPC calls: {rpc_call_count['count']}...")
            return original_get_block(block_id)

        # Fetch timestamps with RPC counting and timing
        print(f"\n1. Running optimized algorithm...")
        with patch.object(w3.eth, "get_block", counting_get_block):
            algo_start = time.time()
            timestamps = get_block_timestamps(w3, blocks, SECONDS_PER_SLOT)
            algo_time = time.time() - algo_start

        print(f"   Done! Time: {algo_time:.2f}s, RPC calls: {rpc_call_count['count']}")

        # Verify all blocks have timestamps
        assert len(timestamps) == len(blocks), f"Missing timestamps: expected {len(blocks)}, got {len(timestamps)}"

        # Fetch all blocks manually (batches of 100) for comparison
        print(f"\n2. Running manual fetch (batches of 100) for comparison...")
        sorted_blocks = sorted(blocks)
        batch_size = 100
        manual_timestamps = {}

        manual_start = time.time()
        for batch_start in range(0, len(sorted_blocks), batch_size):
            batch_end = min(batch_start + batch_size, len(sorted_blocks))
            batch = sorted_blocks[batch_start:batch_end]

            for block_number in batch:
                block_data = w3.eth.get_block(block_number)
                manual_timestamps[block_number] = block_data["timestamp"]

            elapsed = time.time() - manual_start
            print(f"   Fetched {batch_end}/{len(blocks)} blocks... ({elapsed:.1f}s elapsed)")

        manual_time = time.time() - manual_start
        print(f"   Done! Time: {manual_time:.2f}s, RPC calls: {len(blocks)}")

        # Compare timestamps - show sample of comparisons
        print(f"\n3. Verifying all timestamps match (calculated vs actual RPC)...")
        mismatches = []
        sample_to_show = sorted_blocks[:5]  # Show first 5 comparisons

        for i, block_number in enumerate(sorted_blocks):
            calculated_timestamp = timestamps[block_number]
            actual_timestamp = manual_timestamps[block_number]

            # Show first few comparisons as proof
            if block_number in sample_to_show:
                status = "OK" if calculated_timestamp == actual_timestamp else "MISMATCH"
                print(
                    f"   Block {block_number}: calculated={calculated_timestamp}, actual={actual_timestamp} [{status}]"
                )

            if calculated_timestamp != actual_timestamp:
                mismatches.append(
                    {
                        "block": block_number,
                        "calculated": calculated_timestamp,
                        "actual": actual_timestamp,
                        "diff": calculated_timestamp - actual_timestamp,
                    }
                )

        print(f"   ... ({len(blocks) - len(sample_to_show)} more blocks verified)")
        print(f"   Done! Verified {len(blocks)} blocks.")

        print(f"\n{'='*60}")
        print(f"RESULTS:")
        print(f"  Total blocks: {len(blocks)}")
        print(f"{'='*60}")
        print(f"  OPTIMIZED ALGORITHM:")
        print(f"    Time: {algo_time:.2f}s")
        print(f"    RPC calls: {rpc_call_count['count']}")
        print(f"{'='*60}")
        print(f"  MANUAL FETCH (batches of 100):")
        print(f"    Time: {manual_time:.2f}s")
        print(f"    RPC calls: {len(blocks)}")
        print(f"{'='*60}")
        print(f"  IMPROVEMENT:")
        print(f"    Time: {manual_time / algo_time:.1f}x faster")
        print(f"    RPC calls: {len(blocks) / rpc_call_count['count']:.1f}x fewer")
        print(f"{'='*60}")
        print(f"  Correct timestamps: {len(blocks) - len(mismatches)}/{len(blocks)}")
        print(f"  Mismatches: {len(mismatches)}")

        if mismatches:
            print(f"\nMismatched blocks:")
            for m in mismatches[:10]:
                print(f"  Block {m['block']}: calculated={m['calculated']}, actual={m['actual']}, diff={m['diff']}s")
            if len(mismatches) > 10:
                print(f"  ... and {len(mismatches) - 10} more")

        print(f"{'='*60}")

        assert len(mismatches) == 0, f"Found {len(mismatches)} blocks with incorrect timestamps"
