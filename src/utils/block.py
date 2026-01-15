"""Execution layer block utilities."""

from eth_typing import BlockNumber
from web3 import Web3


def get_block_timestamps(
    w3: Web3,
    block_numbers: set[BlockNumber],
    seconds_per_slot: int,
) -> dict[BlockNumber, int]:
    """
    Fetch execution block timestamps for a set of block numbers.

    Uses binary search for missed slot detection to minimize RPC calls:
    1. Fetch first and last block timestamps
    2. If last_ts - first_ts == (last_block - first_block) * seconds_per_slot:
       no missed slots, calculate all intermediate timestamps
    3. If mismatch: binary search to find gap, recurse on sub-ranges

    Since missed slots are rare, this typically requires only 2 RPC calls
    for any number of blocks.
    """
    if not block_numbers:
        return {}

    timestamps: dict[BlockNumber, int] = {}
    _fill_timestamps_recursive(w3, sorted(block_numbers), seconds_per_slot, timestamps)
    return timestamps


def _fill_timestamps_recursive(
    w3: Web3,
    blocks: list[BlockNumber],
    seconds_per_slot: int,
    timestamps: dict[BlockNumber, int],
) -> None:
    """Recursively fill timestamps using binary search for missed slot detection."""
    if not blocks:
        return

    first_block = blocks[0]
    last_block = blocks[-1]

    # Get first timestamp (from cache or RPC)
    if first_block in timestamps:
        first_timestamp = timestamps[first_block]
    else:
        first_block_data = w3.eth.get_block(first_block)
        first_timestamp = int(first_block_data["timestamp"])
        timestamps[first_block] = first_timestamp

    if len(blocks) == 1:
        return

    # Get last timestamp (from cache or RPC)
    if last_block in timestamps:
        last_timestamp = timestamps[last_block]
    else:
        last_block_data = w3.eth.get_block(last_block)
        last_timestamp = int(last_block_data["timestamp"])
        timestamps[last_block] = last_timestamp

    # Check if no missed slots in this range
    expected_last_timestamp = first_timestamp + (last_block - first_block) * seconds_per_slot

    if last_timestamp == expected_last_timestamp:
        # No missed slots - calculate all intermediate timestamps
        for block_number in blocks:
            if block_number not in timestamps:
                offset = block_number - first_block
                timestamps[block_number] = first_timestamp + offset * seconds_per_slot
    elif len(blocks) == 2:
        # Can't split further - both blocks already fetched, nothing more to do
        pass
    else:
        # Missed slots detected - binary search: split and recurse
        mid = len(blocks) // 2
        _fill_timestamps_recursive(w3, blocks[:mid + 1], seconds_per_slot, timestamps)
        _fill_timestamps_recursive(w3, blocks[mid:], seconds_per_slot, timestamps)
