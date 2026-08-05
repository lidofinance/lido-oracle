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


def digest_of(value: Any) -> HexStr:
    """keccak over a canonical encoding of `value`, exactly as the provider returned it."""
    hasher = keccak.new(b'')
    buffer: list[str] = []

    for piece in _encode(value):
        buffer.append(piece)
        if len(buffer) >= _CHUNK_SIZE:
            hasher.update(''.join(buffer).encode())
            buffer.clear()

    hasher.update(''.join(buffer).encode())
    return HexStr('0x' + hasher.digest().hex())


def log_fingerprint(logger: logging.Logger, subject: str, value: Any, **context: Any) -> None:
    """Log a one-line digest of `value`.

    Never raises: this is a diagnostic, and no report may fail over one.
    """
    try:
        digest = digest_of(value)
    except Exception as error:  # pylint: disable=broad-except
        logger.warning({'msg': f'{subject} fingerprint failed.', 'error': repr(error)})
        return

    logger.info({'msg': f'{subject} fingerprint.', 'digest': digest, **context})


def _encode(value: Any) -> Iterator[str]:
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
        yield '['
        for item in value:
            yield from _encode(item)
            yield ','
        yield ']'
    else:
        yield from _encode_composite(value)


def _encode_composite(value: Any) -> Iterator[str]:
    """Everything the hot path in `_encode` does not handle inline."""
    if isinstance(value, bytes):
        yield f'{len(value)}:{value.hex()}'
    elif value is None:
        yield 'null'
    elif isinstance(value, dict):
        # Sorted: an object's field order on the wire carries no meaning, unlike the order
        # of a list, which the beacon state and the deposit queue both depend on.
        yield '{'
        for key in sorted(value):
            yield from _encode(str(key))
            yield '='
            yield from _encode(value[key])
            yield ','
        yield '}'
    elif is_dataclass(value) and not isinstance(value, type):
        yield '{'
        for f in fields(value):
            yield f.name
            yield '='
            yield from _encode(getattr(value, f.name))
            yield ','
        yield '}'
    else:
        raise TypeError(f'Cannot fingerprint {type(value).__name__}')
