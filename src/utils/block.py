"""Execution layer block utilities for efficient timestamp fetching."""

from eth_typing import BlockNumber
from web3 import Web3

# Maximum number of intermediate blocks to batch-fetch at once.
# When a segment has missed slots and fewer intermediates than this threshold,
# we batch-fetch them all instead of continuing binary search.
# Trade-off: higher value = fewer RPC round-trips but more data per call.
BATCH_FETCH_MAX = 10


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
      3) If segment is small (<= BATCH_FETCH_MAX intermediates), batch-fetch all.
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

    # Batch-fetch endpoints, then recursively calculate all timestamps
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
    Falls back to sequential fetching if batch requests aren't supported.
    """
    if not blocks:
        return {}

    try:
        with w3.batch_requests() as batch:
            for b in blocks:
                batch.add(w3.eth.get_block(b))
            results = batch.execute()
        return {b: int(r["timestamp"]) for b, r in zip(blocks, results, strict=True)}
    except Exception:
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
    if len(intermediates) <= BATCH_FETCH_MAX:
        # Small segment: batch-fetch all intermediate blocks
        fetched = _batch_get_ts(w3, intermediates)
        return [first_ts] + [fetched[b] for b in intermediates] + [last_ts]

    # Large segment: binary search - fetch median and recurse on both halves
    mid = len(blocks) // 2
    mid_ts = _get_ts(w3, blocks[mid])

    left = _calculate_timestamps(w3, blocks[: mid + 1], first_ts, mid_ts, seconds_per_slot)
    right = _calculate_timestamps(w3, blocks[mid:], mid_ts, last_ts, seconds_per_slot)

    # Merge: left includes mid, right starts with mid - skip duplicate
    return left + right[1:]
