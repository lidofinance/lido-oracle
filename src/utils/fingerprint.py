"""Compact, comparable fingerprints of the large data sets an oracle report is built from.

Two members log a fingerprint of their own inputs; the difference between the sets falls
out of the two log lines, with no key data changing hands:

- equal `count` and `digest` mean the sets are identical;
- if exactly one entry differs, `xor(a) ^ xor(b)` *is* that entry;
- otherwise the per-bucket digests say which 1/256 of the keyspace to compare, and only
  those few dozen entries need to be exchanged.

Same construction as `scripts/ao_report_debug/keys_digest.py`, so a fingerprint copied out
of a log is comparable with one that tool produced from a live Keys API. How to read them:
`docs/report-divergence-logs.md`.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

from eth_hash.auto import keccak
from eth_typing import HexStr

from src.utils.types import hex_str_to_bytes


BUCKETS: Final = 256

# Bucket digests are only ever compared against each other, 256 at a time, so 8 bytes is
# ample and keeps the whole line inside the 16 KB at which Docker splits a log message.
BUCKET_DIGEST_BYTES: Final = 8


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
        buckets={str(index): digest_of(chunk, BUCKET_DIGEST_BYTES) for index, chunk in sorted(buckets.items())},
        bucket_counts={str(index): len(chunk) for index, chunk in sorted(buckets.items())},
    )


def fingerprint_hex(items: Iterable[str]) -> SetFingerprint:
    """`fingerprint` over 0x-prefixed hex strings — pubkeys, roots, credentials."""
    return fingerprint(hex_str_to_bytes(item) for item in items)


def digest_of(chunks: Iterable[bytes], size: int = 32) -> HexStr:
    """Order-sensitive digest — use for sequences whose order is itself meaningful."""
    hasher = keccak.new(b'')
    for chunk in chunks:
        hasher.update(chunk)
    return HexStr('0x' + hasher.digest()[:size].hex())


def bucket_of(entry: bytes) -> int:
    return entry[0] * BUCKETS // 256 if entry else 0


def log_fingerprint(
    logger: logging.Logger, subject: str, items: Iterable[bytes], buckets: bool = True, **extra: Any
) -> None:
    """Emit `subject` as a small summary line, and optionally the bucket digests.

    Split so log shipping can drop the bulk line and still detect a divergence from the
    summary. `buckets=False` where the summary alone answers the question.

    Never raises: this is a diagnostic, and no report may fail over one.
    """
    try:
        fp = fingerprint(items)
    except Exception as error:  # pylint: disable=broad-except
        logger.warning({'msg': f'{subject} fingerprint failed.', 'error': repr(error)})
        return

    logger.info({'msg': f'{subject} fingerprint.', **fp.summary, **extra})

    if buckets:
        logger.info({'msg': f'{subject} buckets.', 'bucket_counts': fp.bucket_counts, 'buckets': fp.buckets})


def log_fingerprint_hex(
    logger: logging.Logger, subject: str, items: Iterable[str], buckets: bool = True, **extra: Any
) -> None:
    """`log_fingerprint` over 0x-prefixed hex strings."""
    log_fingerprint(logger, subject, (hex_str_to_bytes(item) for item in items), buckets, **extra)
