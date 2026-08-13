"""One comparable digest per large response an oracle report is built from.

Equal digests mean two members read the same inputs — that is the whole claim. The digest
covers the parsed value, not the raw body: the state response envelope carries a per-node
`execution_optimistic`, so raw bytes differ between two correct members whenever one node's
execution client lags. Which lines to compare: `docs/report-divergence.md`.
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
        logger.warning({'msg': f'{subject} fingerprint failed.', 'error': repr(error), **context})
        return

    logger.info({'msg': f'{subject} fingerprint.', 'digest': digest, **context})


def _encode(value: Any) -> Iterator[str]:
    """Canonical encoding: self-delimiting, and independent of how the response arrived.

    Yields many small pieces rather than building one string — a mainnet beacon state does
    not fit in memory twice.
    """
    scalar = _scalar(value)
    if scalar is not None:
        yield scalar
    elif isinstance(value, (list, tuple)):
        yield from _encode_sequence(value)
    elif isinstance(value, dict):
        # Sorted: an object's field order on the wire carries no meaning, unlike the order
        # of a list, which the beacon state and the deposit queue both depend on.
        yield '{'
        for key in sorted(value):
            yield _str(str(key))
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


def _scalar(value: Any) -> str | None:
    """The encoding of a leaf value, or None if `value` is not one.

    Shared by both paths in `_encode_sequence` so the two can never disagree.
    """
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _str(value)
    if value is None:
        return 'null'
    if isinstance(value, bytes):
        return f'{len(value)}:{value.hex()}'
    return None


def _str(value: str) -> str:
    """Length-prefixed, so 'ab' + 'c' cannot encode the same as 'a' + 'bc' and no character
    needs escaping."""
    return f'{len(value)}:{value}'


def _encode_sequence(value: list | tuple) -> Iterator[str]:
    records = _flat_record_type(value)
    if records is None:
        yield '['
        for item in value:
            yield from _encode(item)
            yield ','
        yield ']'
        return

    # Same output as the branch above, but without a generator per field: 10 pieces a record
    # rather than 35, and none of the ~21M nested generators that cost. Measured on a
    # mainnet state (2.3M validators): 16.6 s against 8.2 s.
    cls, names = records
    yield '['
    for item in value:
        if type(item) is not cls:
            raise TypeError(f'Mixed record types in sequence: {cls.__name__} and {type(item).__name__}')
        yield '{'
        for name in names:
            scalar = _scalar(getattr(item, name))
            if scalar is None:
                raise TypeError(f'{cls.__name__}.{name} is not a leaf value')
            yield f'{name}={scalar},'
        yield '},'
    yield ']'


def _flat_record_type(value: list | tuple) -> tuple[type, tuple[str, ...]] | None:
    """`(type, field names)` when `value` holds dataclasses with leaf-only fields, else None.

    Probes the first entry only; the loop above rejects any later entry of another type, and
    a non-leaf field raises rather than being encoded some other way.
    """
    if not value:
        return None
    head = value[0]
    cls = type(head)
    if not is_dataclass(cls):
        return None
    names = tuple(f.name for f in fields(cls))
    if any(_scalar(getattr(head, name)) is None for name in names):
        return None
    return cls, names
