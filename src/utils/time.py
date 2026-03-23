"""
Utilities for time conversion between milliseconds and seconds.
"""

import math


def ms_to_seconds(milliseconds: int) -> float:
    """Convert milliseconds to seconds with precise float division."""
    return milliseconds / 1000


def seconds_to_ms(seconds: float | int) -> int:
    """Convert seconds to milliseconds with integer result."""
    return int(seconds * 1000)


def eip7805_float_seconds_to_int(seconds: float) -> int:
    """
    Convert float seconds to integer seconds for EIP-7805 SLOT_DURATION_MS migration.

    https://github.com/ethereum/consensus-specs/pull/4926

    This function is used when converting time calculations that now use float seconds
    (due to precise SLOT_DURATION_MS / 1000 conversion) back to integer seconds for
    APIs and calculations that require integer timestamps.

    EIP-7805 Context:
    - ethereum/consensus-specs#4926 replaces SECONDS_PER_SLOT (12 int) with SLOT_DURATION_MS (12000 int)
    - This enables precise non-round slot durations (e.g., 12.5s = 12500ms)
    - However, many timestamp calculations still need integer seconds for compatibility

    Rounding Algorithm: FLOOR (truncation toward zero)

    Why FLOOR:
    1. Conservative approach - timestamps should not exceed actual time
    2. Consistent with Python's int() behavior for positive numbers
    3. Prevents "future timestamp" issues in blockchain contexts
    4. Matches historical behavior when seconds_per_slot was int

    Example:
    - 12.7 seconds → 12 seconds (not 13)
    - 86400.3 seconds → 86400 seconds

    Args:
        seconds: Float seconds to convert

    Returns:
        Integer seconds using floor rounding

    Raises:
        TypeError: If seconds is not a number
    """
    if not isinstance(seconds, (int, float)):
        raise TypeError(f"Expected int or float, got {type(seconds)}")

    # Use math.floor for explicit floor rounding behavior
    # This is equivalent to int() for positive numbers but more explicit
    return int(math.floor(seconds))
