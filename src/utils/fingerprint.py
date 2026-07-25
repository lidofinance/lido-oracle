"""Compact, comparable fingerprints of the large data sets an oracle report is built from.

Two members log a fingerprint of their own inputs, and comparing the two log lines answers
the first question an incident asks — did we read the same data? — without either operator
sharing any of it:

- equal `count` and `digest` mean the sets are identical;
- if exactly one entry differs, `xor(a) ^ xor(b)` *is* that entry.

Finding *which* entries differ when more than one does is deliberately not solved here: it
needs per-slice detail costing orders of magnitude more log volume than these three fields,
for a case that has not yet occurred. How to read them: `docs/report-divergence-logs.md`.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from eth_hash.auto import keccak
from eth_typing import HexStr

from src.utils.types import hex_str_to_bytes


@dataclass(frozen=True)
class SetFingerprint:
    """Order-independent fingerprint of a set of equal-length byte strings."""

    count: int
    digest: HexStr
    xor: HexStr

    @property
    def summary(self) -> dict[str, Any]:
        return {'count': self.count, 'digest': self.digest, 'xor': self.xor}


def fingerprint(items: Iterable[bytes]) -> SetFingerprint:
    entries = sorted(items)

    hasher = keccak.new(b'')
    xor_acc = 0
    width = 0
    for entry in entries:
        hasher.update(entry)
        xor_acc ^= int.from_bytes(entry, 'big')
        width = max(width, len(entry))

    return SetFingerprint(
        count=len(entries),
        digest=HexStr('0x' + hasher.digest().hex()),
        xor=HexStr('0x' + xor_acc.to_bytes(width, 'big').hex()),
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


def log_fingerprint(logger: logging.Logger, subject: str, items: Iterable[bytes], **extra: Any) -> None:
    """Log a one-line fingerprint of `items`.

    Never raises: this is a diagnostic, and no report may fail over one.
    """
    try:
        fp = fingerprint(items)
    except Exception as error:  # pylint: disable=broad-except
        logger.warning({'msg': f'{subject} fingerprint failed.', 'error': repr(error)})
        return

    logger.info({'msg': f'{subject} fingerprint.', **fp.summary, **extra})


def log_fingerprint_hex(logger: logging.Logger, subject: str, items: Iterable[str], **extra: Any) -> None:
    """`log_fingerprint` over 0x-prefixed hex strings."""
    log_fingerprint(logger, subject, (hex_str_to_bytes(item) for item in items), **extra)
