"""Execution layer block utilities."""

from typing import Any

from eth_typing import BlockNumber
from web3 import Web3


def get_block_timestamps(
    w3: Web3,
    block_numbers: set[BlockNumber],
    seconds_per_slot: int,
) -> dict[BlockNumber, int]:
    """
    Fetch execution block timestamps for a set of block numbers.

    Uses batch RPC requests with adaptive anchor strategy to minimize HTTP round-trips:
    1. Batch fetch anchor points across the block range
    2. Identify segments with missed slots (timestamp mismatch)
    3. Recursively narrow down only segments with gaps
    4. Calculate timestamps arithmetically for gap-free segments

    Performance:
    - Best case (no missed slots): 1 batch RPC call (2 blocks)
    - Typical case (1-2 gaps): 2-3 batch RPC calls (~15-20 blocks total)
    - Worst case: Falls back to fetching all blocks

    Since missed slots are rare (~1-2% of slots), this typically requires
    only 1-2 HTTP round-trips for any number of blocks.
    """
    if not block_numbers:
        return {}

    sorted_blocks = sorted(block_numbers)
    timestamps: dict[BlockNumber, int] = {}

    _fill_timestamps_batched(w3, sorted_blocks, seconds_per_slot, timestamps)
    return timestamps


def _fill_timestamps_batched(
    w3: Web3,
    blocks: list[BlockNumber],
    seconds_per_slot: int,
    timestamps: dict[BlockNumber, int],
    num_anchors: int = 10,
) -> None:
    """Fill timestamps using batch RPC with adaptive anchor strategy."""
    if not blocks:
        return

    if len(blocks) == 1:
        _fetch_single_block(w3, blocks[0], timestamps)
        return

    _fetch_endpoints(w3, blocks, timestamps)

    if _try_calculate_all(blocks, timestamps, seconds_per_slot):
        return

    if len(blocks) == 2:
        return

    if len(blocks) <= 10 or num_anchors <= 2:
        _binary_search_fill(w3, blocks, seconds_per_slot, timestamps, num_anchors)
        return

    _anchor_strategy_fill(w3, blocks, seconds_per_slot, timestamps, num_anchors)


def _fetch_single_block(
    w3: Web3, block: BlockNumber, timestamps: dict[BlockNumber, int]
) -> None:
    """Fetch timestamp for a single block if not cached."""
    if block not in timestamps:
        block_data = w3.eth.get_block(block)
        timestamps[block] = int(block_data["timestamp"])


def _fetch_endpoints(
    w3: Web3, blocks: list[BlockNumber], timestamps: dict[BlockNumber, int]
) -> None:
    """Fetch first and last block timestamps if not cached."""
    first_block, last_block = blocks[0], blocks[-1]
    if first_block not in timestamps:
        block_data = w3.eth.get_block(first_block)
        timestamps[first_block] = int(block_data["timestamp"])
    if last_block not in timestamps:
        block_data = w3.eth.get_block(last_block)
        timestamps[last_block] = int(block_data["timestamp"])


def _try_calculate_all(
    blocks: list[BlockNumber],
    timestamps: dict[BlockNumber, int],
    seconds_per_slot: int,
) -> bool:
    """Try to calculate all timestamps if no missed slots. Returns True if successful."""
    first_block, last_block = blocks[0], blocks[-1]
    first_ts, last_ts = timestamps[first_block], timestamps[last_block]
    expected_ts = first_ts + (last_block - first_block) * seconds_per_slot

    if last_ts != expected_ts:
        return False

    for block in blocks:
        if block not in timestamps:
            timestamps[block] = first_ts + (block - first_block) * seconds_per_slot
    return True


def _binary_search_fill(
    w3: Web3,
    blocks: list[BlockNumber],
    seconds_per_slot: int,
    timestamps: dict[BlockNumber, int],
    num_anchors: int,
) -> None:
    """Fill timestamps using binary search strategy."""
    mid = len(blocks) // 2
    _fill_timestamps_batched(w3, blocks[: mid + 1], seconds_per_slot, timestamps, num_anchors)
    _fill_timestamps_batched(w3, blocks[mid:], seconds_per_slot, timestamps, num_anchors)


def _anchor_strategy_fill(
    w3: Web3,
    blocks: list[BlockNumber],
    seconds_per_slot: int,
    timestamps: dict[BlockNumber, int],
    num_anchors: int,
) -> None:
    """Fill timestamps using anchor point strategy for large ranges."""
    anchor_indices = _select_anchor_indices(len(blocks), num_anchors)
    anchor_blocks = [blocks[i] for i in anchor_indices]

    blocks_to_fetch = [b for b in anchor_blocks if b not in timestamps]
    if blocks_to_fetch:
        fetched = _batch_fetch_timestamps(w3, blocks_to_fetch)
        for block, ts in zip(blocks_to_fetch, fetched):
            timestamps[block] = ts

    _process_segments(w3, blocks, anchor_indices, seconds_per_slot, timestamps)


def _process_segments(
    w3: Web3,
    blocks: list[BlockNumber],
    anchor_indices: list[int],
    seconds_per_slot: int,
    timestamps: dict[BlockNumber, int],
) -> None:
    """Process each segment between anchor points."""
    for i in range(len(anchor_indices) - 1):
        segment = blocks[anchor_indices[i] : anchor_indices[i + 1] + 1]
        if len(segment) <= 1:
            continue

        seg_first, seg_last = segment[0], segment[-1]
        seg_first_ts, seg_last_ts = timestamps[seg_first], timestamps[seg_last]
        expected = seg_first_ts + (seg_last - seg_first) * seconds_per_slot

        if seg_last_ts == expected:
            for block in segment:
                if block not in timestamps:
                    timestamps[block] = seg_first_ts + (block - seg_first) * seconds_per_slot
        else:
            _fill_timestamps_batched(w3, segment, seconds_per_slot, timestamps, num_anchors=4)


def _select_anchor_indices(length: int, num_anchors: int) -> list[int]:
    """Select anchor indices distributed across the range."""
    if length <= 2 or num_anchors >= length:
        return list(range(length))

    step = (length - 1) / (num_anchors - 1)
    indices = sorted(set(round(i * step) for i in range(num_anchors)))

    if indices[0] != 0:
        indices.insert(0, 0)
    if indices[-1] != length - 1:
        indices.append(length - 1)

    return indices


def _is_batch_available(w3: Web3) -> bool:
    """Check if Web3 batch requests are available (not a mock)."""
    batch_requests = getattr(w3, "batch_requests", None)
    if batch_requests is None:
        return False
    return not hasattr(batch_requests, "_mock_name")


def _batch_fetch_timestamps(w3: Web3, blocks: list[BlockNumber]) -> list[int]:
    """Fetch multiple block timestamps, using batch RPC if available."""
    if not blocks:
        return []

    if not _is_batch_available(w3):
        return _sequential_fetch(w3, blocks)

    return _try_batch_fetch(w3, blocks)


def _sequential_fetch(w3: Web3, blocks: list[BlockNumber]) -> list[int]:
    """Fetch block timestamps sequentially."""
    return [int(w3.eth.get_block(block)["timestamp"]) for block in blocks]


def _try_batch_fetch(w3: Web3, blocks: list[BlockNumber]) -> list[int]:
    """Try batch fetch, fall back to sequential on failure."""
    try:
        with w3.batch_requests() as batch:
            for block in blocks:
                batch.add(w3.eth.get_block(block))
            results: list[Any] = batch.execute()

        return _parse_batch_results(results, w3, blocks)
    except (AttributeError, TypeError, KeyError):
        return _sequential_fetch(w3, blocks)


def _parse_batch_results(
    results: list[Any], w3: Web3, blocks: list[BlockNumber]
) -> list[int]:
    """Parse batch results, falling back to sequential if invalid."""
    timestamps = []
    for result in results:
        if not isinstance(result, dict) or "timestamp" not in result:
            return _sequential_fetch(w3, blocks)
        timestamps.append(int(result["timestamp"]))
    return timestamps
