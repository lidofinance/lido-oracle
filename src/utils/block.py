"""Execution layer block utilities for efficient timestamp fetching."""

from typing import Any

from eth_typing import BlockNumber
from web3 import Web3

from src.metrics.logging import logging
from src.variables import BLOCK_BATCH_SIZE_LIMIT

logger = logging.getLogger(__name__)

def _should_batch(count: int) -> bool:
    """
    Determine if batching should be used for the given number of blocks.
    Batching is disabled when BLOCK_BATCH_SIZE_LIMIT=1 or count <= 1.
    """
    return BLOCK_BATCH_SIZE_LIMIT > 1 and count > 1


def get_block_timestamps(
    w3: Web3,
    block_numbers: set[BlockNumber],
    seconds_per_slot: int,
) -> dict[BlockNumber, int]:
    """
    Fetch execution block timestamps for a set of block numbers.

    Uses a hybrid strategy to minimize RPC round-trips:
      1) Batch-fetch first and last block timestamps.
      2) If timestamps match expected difference (no missed slots), calculate
         all intermediate timestamps arithmetically.
      3) If segment is small (<= BLOCK_BATCH_SIZE_LIMIT intermediates), batch-fetch all.
      4) Otherwise, binary search: fetch median and recurse on both halves.

    Performance:
      - Best case (no missed slots): 1 batch RPC call (2 blocks)
      - Small segments with gaps: 1 additional batch call
      - Large segments with gaps: O(log n) calls to isolate gaps
    """
    if not block_numbers:
        return {}

    blocks = sorted(block_numbers)

    if len(blocks) == 1:
        return {blocks[0]: _get_ts(w3, blocks[0])}

    # Fetch endpoints, then recursively calculate all timestamps
    endpoints = _batch_get_ts(w3, [blocks[0], blocks[-1]])
    first_ts = endpoints[blocks[0]]
    last_ts = endpoints[blocks[-1]]

    timestamps = _calculate_timestamps(w3, blocks, first_ts, last_ts, seconds_per_slot)
    return dict(zip(blocks, timestamps, strict=True))


def _get_ts(w3: Web3, block: BlockNumber) -> int:
    """Fetch timestamp for a single block."""
    return int(w3.eth.get_block(block)["timestamp"])


def _batch_get_ts(w3: Web3, blocks: list[BlockNumber]) -> dict[BlockNumber, int]:
    """
    Batch-fetch timestamps for multiple blocks in one RPC call.
    Falls back to sequential fetching if batching is disabled or not supported.
    """
    if not blocks:
        return {}

    # If batching is disabled, use sequential requests
    if not _should_batch(len(blocks)):
        return {b: _get_ts(w3, b) for b in blocks}

    try:
        with w3.batch_requests() as batch:
            for b in blocks:
                batch.add(w3.eth.get_block(b))
            results: list[Any] = batch.execute()
        return {b: int(r["timestamp"]) for b, r in zip(blocks, results, strict=True)}
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning({
            'msg': 'Batch request for block timestamps failed, falling back to sequential requests.',
            'error': str(e),
        })
        return {b: _get_ts(w3, b) for b in blocks}


def _calculate_timestamps(
    w3: Web3,
    blocks: list[BlockNumber],
    first_ts: int,
    last_ts: int,
    seconds_per_slot: int,
) -> list[int]:
    """
    Calculate timestamps for sorted blocks given known endpoint timestamps.
    Returns list of timestamps in same order as input blocks.
    """
    if len(blocks) <= 2:
        return [first_ts] if len(blocks) == 1 else [first_ts, last_ts]

    # Check for missed slots: if block N is at time T, block N+k should be at T + k*slot_time
    expected_last_ts = first_ts + (blocks[-1] - blocks[0]) * seconds_per_slot
    if expected_last_ts == last_ts:
        # No missed slots: calculate all timestamps arithmetically
        base = blocks[0]
        return [first_ts + (b - base) * seconds_per_slot for b in blocks]

    # Missed slot(s) detected
    intermediates = blocks[1:-1]
    if len(intermediates) <= BLOCK_BATCH_SIZE_LIMIT:
        # Small segment: fetch all intermediate blocks
        fetched = _batch_get_ts(w3, intermediates)
        return [first_ts] + [fetched[b] for b in intermediates] + [last_ts]

    # Large segment: binary search - fetch median and recurse on both halves
    mid = len(blocks) // 2
    mid_ts = _get_ts(w3, blocks[mid])

    left = _calculate_timestamps(w3, blocks[: mid + 1], first_ts, mid_ts, seconds_per_slot)
    right = _calculate_timestamps(w3, blocks[mid:], mid_ts, last_ts, seconds_per_slot)

    # Merge: left includes mid, right starts with mid - skip duplicate
    return left + right[1:]
