"""One comparable digest per large response an oracle report is built from.

When members submit different report hashes they disagree about an *input*. The inputs big
enough to hide a disagreement — the beacon state (~900 MB) and the Keys API used-key set
(~485k keys) — cannot be logged as-is, so each is logged as a single digest instead. Two
members compare one line each: equal digests mean the responses were identical, and that is
the whole question the log answers.

It deliberately does not say *which* entry differs. Naming it needs the data itself, which
is still on the live Keys API instances or on an archive node; pre-staging an answer in the
logs would cost orders of magnitude more volume every cycle. Which lines to compare, in
which order: the "Report divergence" section of `README.md`.

The digest covers the *parsed* response, not the bytes on the wire. Consensus clients
serialise the same state differently — key order, whitespace, numeric formatting — so a
digest of the raw body would differ between two correct members every cycle and mean
nothing.
"""

import logging
from collections.abc import Iterator
from dataclasses import fields, is_dataclass
from typing import Any

from eth_hash.auto import keccak
from eth_typing import HexStr


# Pieces buffered between keccak updates. Hashing a mainnet beacon state is ~10M pieces;
# feeding them one at a time triples the wall time.
_CHUNK_SIZE = 4096


def digest_of(value: Any, *, ordered: bool = True) -> HexStr:
    """keccak over a canonical encoding of `value`.

    `ordered=False` treats every list as a set, by sorting per-entry digests instead of
    encoding entries in place. Use it for a response whose row order is incidental — the
    Keys API promises none, so an order-sensitive digest would flag two identical key sets
    as different. The beacon state is the opposite case: its list order is part of the
    state, so it is fingerprinted ordered.
    """
    hasher = keccak.new(b'')
    buffer: list[str] = []

    for piece in _encode(value, ordered):
        buffer.append(piece)
        if len(buffer) >= _CHUNK_SIZE:
            hasher.update(''.join(buffer).encode())
            buffer.clear()

    hasher.update(''.join(buffer).encode())
    return HexStr('0x' + hasher.digest().hex())


def log_fingerprint(logger: logging.Logger, subject: str, value: Any, *, ordered: bool = True, **context: Any) -> None:
    """Log a one-line digest of `value`.

    Never raises: this is a diagnostic, and no report may fail over one.
    """
    try:
        digest = digest_of(value, ordered=ordered)
    except Exception as error:  # pylint: disable=broad-except
        logger.warning({'msg': f'{subject} fingerprint failed.', 'error': repr(error)})
        return

    logger.info({'msg': f'{subject} fingerprint.', 'digest': digest, **context})


def _encode(value: Any, ordered: bool) -> Iterator[str]:
    """Canonical encoding: self-delimiting, and independent of how the response arrived.

    Yields many small pieces rather than building one string — a mainnet beacon state does
    not fit in memory twice.
    """
    if isinstance(value, bool):
        yield 'true' if value else 'false'
    elif isinstance(value, int):
        yield str(value)
    elif isinstance(value, str):
        # Length-prefixed, so 'ab' + 'c' cannot encode the same as 'a' + 'bc' and no
        # character needs escaping.
        yield f'{len(value)}:{value}'
    elif isinstance(value, (list, tuple)):
        yield from _encode_sequence(value, ordered)
    else:
        yield from _encode_composite(value, ordered)


def _encode_composite(value: Any, ordered: bool) -> Iterator[str]:
    """Everything the hot path in `_encode` does not handle inline."""
    if isinstance(value, bytes):
        yield f'{len(value)}:{value.hex()}'
    elif value is None:
        yield 'null'
    elif isinstance(value, dict):
        # Sorted: an object's field order on the wire carries no meaning.
        yield '{'
        for key in sorted(value):
            yield from _encode(str(key), ordered)
            yield '='
            yield from _encode(value[key], ordered)
            yield ','
        yield '}'
    elif is_dataclass(value) and not isinstance(value, type):
        yield '{'
        for f in fields(value):
            yield f.name
            yield '='
            yield from _encode(getattr(value, f.name), ordered)
            yield ','
        yield '}'
    else:
        raise TypeError(f'Cannot fingerprint {type(value).__name__}')


def _encode_sequence(value: list | tuple, ordered: bool) -> Iterator[str]:
    if ordered:
        yield '['
        for item in value:
            yield from _encode(item, ordered)
            yield ','
        yield ']'
        return

    # Set semantics. Sorting the entries themselves would hold the whole response in memory
    # a second time; sorting their digests costs 32 bytes an entry.
    yield '{'
    for entry_digest in sorted(digest_of(item, ordered=False) for item in value):
        yield entry_digest
        yield ','
    yield '}'
