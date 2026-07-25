"""Compact, comparable fingerprints of the large data sets an oracle report is built from.

Two members log a fingerprint of their own inputs; the difference between the sets falls
out of the two log lines, with no key data changing hands. How to read them:
``docs/report-divergence-logs.md``.

``digest`` and ``buckets`` match the construction in
``scripts/ao_report_debug/keys_digest.py``, so a fingerprint copied out of a log is
comparable with one that tool produced from a live Keys API.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

from eth_hash.auto import keccak
from eth_typing import HexStr

from src.utils.types import hex_str_to_bytes


BUCKETS: Final = 256

# With 4 hashes per entry an IBLT decodes reliably below ~0.72 * cells *differing* entries
# and abruptly decodes nothing past it. 512 cells -> ~380 differences for ~61 KB per set.
IBLT_CELLS: Final = 512
IBLT_HASHES: Final = 4
_IBLT_VERSION: Final = 1
_IBLT_COUNT_BYTES: Final = 4
_IBLT_CHECKSUM_BYTES: Final = 8
_IBLT_HEADER_BYTES: Final = 5


@dataclass(frozen=True)
class SetFingerprint:
    """Order-independent fingerprint of a set of equal-length byte strings."""

    count: int
    digest: HexStr
    xor: HexStr
    buckets: dict[str, HexStr]
    bucket_counts: dict[str, int]

    @property
    def summary(self) -> dict[str, Any]:
        """The part small enough to sit inline in a routine log line."""
        return {'count': self.count, 'digest': self.digest, 'xor': self.xor}


def fingerprint(items: Iterable[bytes]) -> SetFingerprint:
    entries = sorted(items)

    hasher = keccak.new(b'')
    xor_acc = 0
    width = 0
    buckets: dict[int, list[bytes]] = {}

    for entry in entries:
        hasher.update(entry)
        xor_acc ^= int.from_bytes(entry, 'big')
        width = max(width, len(entry))
        buckets.setdefault(bucket_of(entry), []).append(entry)

    return SetFingerprint(
        count=len(entries),
        digest=HexStr('0x' + hasher.digest().hex()),
        xor=HexStr('0x' + xor_acc.to_bytes(width, 'big').hex()),
        # `entries` is sorted, so each bucket is built in sorted order already.
        buckets={str(index): digest_of(chunk) for index, chunk in sorted(buckets.items())},
        bucket_counts={str(index): len(chunk) for index, chunk in sorted(buckets.items())},
    )


def fingerprint_hex(items: Iterable[str]) -> SetFingerprint:
    """`fingerprint` over 0x-prefixed hex strings — pubkeys, roots, credentials."""
    return fingerprint(hex_str_to_bytes(item) for item in items)


def digest_of(chunks: Iterable[bytes]) -> HexStr:
    """Order-sensitive digest — use for sequences whose order is itself meaningful."""
    hasher = keccak.new(b'')
    for chunk in chunks:
        hasher.update(chunk)
    return HexStr('0x' + hasher.digest().hex())


def bucket_of(entry: bytes) -> int:
    return entry[0] * BUCKETS // 256 if entry else 0


@dataclass(frozen=True)
class IBLTDiff:
    """What two sketches, subtracted and peeled, revealed."""

    only_in_left: list[bytes]
    only_in_right: list[bytes]
    decoded: bool

    @property
    def total(self) -> int:
        return len(self.only_in_left) + len(self.only_in_right)


def _iblt_positions(digest: bytes, cells: int) -> set[int]:
    return {int.from_bytes(digest[i * 8 : (i + 1) * 8], 'big') % cells for i in range(IBLT_HASHES)}


def iblt_sketch(items: Iterable[bytes], cells: int = IBLT_CELLS) -> HexStr:
    """Build an invertible Bloom lookup table over a set of equal-length entries.

    Each entry is XOR-ed into `IBLT_HASHES` cells rather than one, so subtracting two
    sketches leaves cells holding a single differing entry, which `iblt_diff` peels out.
    """
    entries = list(items)
    width = max((len(entry) for entry in entries), default=0)

    # Accumulate as integers: XOR-ing 384-bit ints happens in C, where the equivalent
    # per-byte loop over ~2M cell updates does not.
    counts = [0] * cells
    xors = [0] * cells
    checksums = [0] * cells

    for entry in entries:
        digest = keccak(entry)
        value = int.from_bytes(entry, 'big')
        checksum = int.from_bytes(digest[:_IBLT_CHECKSUM_BYTES], 'big')
        for position in _iblt_positions(digest, cells):
            counts[position] += 1
            xors[position] ^= value
            checksums[position] ^= checksum

    blob = bytearray(_IBLT_VERSION.to_bytes(1, 'big') + width.to_bytes(2, 'big') + cells.to_bytes(2, 'big'))
    for position in range(cells):
        blob += counts[position].to_bytes(_IBLT_COUNT_BYTES, 'big')
        blob += xors[position].to_bytes(width, 'big')
        blob += checksums[position].to_bytes(_IBLT_CHECKSUM_BYTES, 'big')
    return HexStr('0x' + blob.hex())


def iblt_diff(left: str, right: str) -> IBLTDiff:
    """Subtract two sketches and peel out every entry only one side had.

    `decoded` is False when the difference exceeded what the sketch can resolve; the
    entries returned alongside it are still genuine, just incomplete.
    """
    left_width, cells, left_cells = _iblt_parse(left)
    right_width, right_cells_count, right_cells = _iblt_parse(right)
    if (left_width, cells) != (right_width, right_cells_count):
        raise ValueError(f'Sketch shape mismatch: {left_width}/{cells} vs {right_width}/{right_cells_count}')

    counts = [left_cells[i][0] - right_cells[i][0] for i in range(cells)]
    xors = [left_cells[i][1] ^ right_cells[i][1] for i in range(cells)]
    checksums = [left_cells[i][2] ^ right_cells[i][2] for i in range(cells)]

    def is_pure(position: int) -> bool:
        if abs(counts[position]) != 1:
            return False
        candidate = xors[position].to_bytes(left_width, 'big')
        return checksums[position] == int.from_bytes(keccak(candidate)[:_IBLT_CHECKSUM_BYTES], 'big')

    only_in_left: list[bytes] = []
    only_in_right: list[bytes] = []

    pure = [position for position in range(cells) if is_pure(position)]
    while pure:
        position = pure.pop()
        if not is_pure(position):
            continue  # already peeled by a neighbour

        sign = counts[position]
        value = xors[position]
        entry = value.to_bytes(left_width, 'big')
        (only_in_left if sign > 0 else only_in_right).append(entry)

        digest = keccak(entry)
        checksum = int.from_bytes(digest[:_IBLT_CHECKSUM_BYTES], 'big')
        for neighbour in _iblt_positions(digest, cells):
            counts[neighbour] -= sign
            xors[neighbour] ^= value
            checksums[neighbour] ^= checksum
            if is_pure(neighbour):
                pure.append(neighbour)

    decoded = not any(counts) and not any(xors)
    return IBLTDiff(sorted(only_in_left), sorted(only_in_right), decoded)


def _iblt_parse(sketch: str) -> tuple[int, int, list[tuple[int, int, int]]]:
    blob = hex_str_to_bytes(sketch)
    version = blob[0]
    if version != _IBLT_VERSION:
        raise ValueError(f'Unsupported sketch version {version}')

    width = int.from_bytes(blob[1:3], 'big')
    cells = int.from_bytes(blob[3:5], 'big')
    stride = _IBLT_COUNT_BYTES + width + _IBLT_CHECKSUM_BYTES
    if len(blob) != _IBLT_HEADER_BYTES + cells * stride:
        raise ValueError('Truncated sketch')

    parsed = []
    for position in range(cells):
        start = _IBLT_HEADER_BYTES + position * stride
        count = int.from_bytes(blob[start : start + _IBLT_COUNT_BYTES], 'big')
        xor = int.from_bytes(blob[start + _IBLT_COUNT_BYTES : start + _IBLT_COUNT_BYTES + width], 'big')
        checksum = int.from_bytes(blob[start + _IBLT_COUNT_BYTES + width : start + stride], 'big')
        parsed.append((count, xor, checksum))
    return width, cells, parsed


def log_fingerprint(
    logger: logging.Logger,
    subject: str,
    items: Iterable[bytes],
    cells: int = IBLT_CELLS,
    sketch: bool = True,
    **extra: Any,
) -> None:
    """Emit `subject` as a small summary line, then the bulk sketch on its own line.

    Split so log shipping can drop the sketch and still detect a divergence from the
    summary. `sketch=False` where the summary alone answers the question and ~61 KB a cycle
    is not worth it.

    Never raises: this is a diagnostic, and no report may fail over one.
    """
    entries = None
    try:
        entries = list(items)
        fp = fingerprint(entries)
    except Exception as error:  # pylint: disable=broad-except
        logger.warning({'msg': f'{subject} fingerprint failed.', 'error': repr(error)})
        return

    logger.info({'msg': f'{subject} fingerprint.', **fp.summary, **extra})

    if not sketch:
        return

    try:
        blob = iblt_sketch(entries, cells)
    except Exception as error:  # pylint: disable=broad-except
        logger.warning({'msg': f'{subject} sketch failed.', 'error': repr(error)})
        return

    logger.info(
        {
            'msg': f'{subject} sketch.',
            'cells': cells,
            'bucket_counts': fp.bucket_counts,
            'iblt': blob,
        }
    )


def log_fingerprint_hex(
    logger: logging.Logger,
    subject: str,
    items: Iterable[str],
    cells: int = IBLT_CELLS,
    sketch: bool = True,
    **extra: Any,
) -> None:
    """`log_fingerprint` over 0x-prefixed hex strings."""
    log_fingerprint(logger, subject, (hex_str_to_bytes(item) for item in items), cells, sketch, **extra)
