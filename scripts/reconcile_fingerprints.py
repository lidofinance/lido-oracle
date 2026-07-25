#!/usr/bin/env python3
"""Recover the exact entries two oracle members disagreed about, from their logs.

Each member logs an IBLT sketch of every large input it built its report from — the Keys
API used-key set, the pending deposit queue, the selected pending validators. Subtracting
two sketches and peeling them yields the full symmetric difference: every key or deposit
one member had and the other did not, and which side was missing it. No key data has to be
exchanged between operators; the two log lines are enough.

Usage:

    # every part of the sketch, from each member's log, for the same reference slot
    grep '"msg": "Pending Lido validators sketch."' member-a.log > a.json
    grep '"msg": "Pending Lido validators sketch."' member-b.log > b.json

    python3 scripts/reconcile_fingerprints.py a.json b.json

Accepts the sketch log lines (one file per member, all parts) or a bare 0x sketch, as a
file or inline. If a reference slot appears more than once in a log, keep only the parts
from the run you mean.
"""

import argparse
import json
import os
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.utils.fingerprint import iblt_diff  # noqa: E402


def read_sketch(source: str) -> str:
    """Reassemble a sketch from its log lines.

    A sketch is emitted in numbered parts, because Docker splits any log message over 16 KB
    and not every collector puts it back together. Missing parts are an error here rather
    than a sketch that quietly decodes to nothing.
    """
    if os.path.exists(source):
        with open(source) as handle:
            raw = handle.read().strip()
    else:
        raw = source.strip()

    if raw.startswith('0x'):
        return raw

    parts: dict[int, str] = {}
    expected = None
    for number, text in enumerate(raw.splitlines(), start=1):
        if not text.strip():
            continue
        try:
            line = json.loads(text)
        except json.JSONDecodeError as error:
            raise SystemExit(f'{source} line {number}: not JSON ({error}). Truncated by the log pipeline?') from error
        if 'iblt' not in line:
            raise SystemExit(f"{source} line {number}: no 'iblt' field — is this a '<subject> sketch.' log line?")
        parts[line.get('part', 1)] = line['iblt']
        expected = line.get('parts', 1)

    if not parts:
        raise SystemExit(f'{source}: no sketch lines found')

    missing = [n for n in range(1, (expected or 1) + 1) if n not in parts]
    if missing:
        raise SystemExit(
            f'{source}: missing part(s) {missing} of {expected}. '
            f'Grep all of them: grep \'"msg": "<subject> sketch."\' <log>'
        )

    return '0x' + ''.join(parts[n] for n in sorted(parts))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('left', help="First member's sketch: log line, file, or bare 0x hex")
    parser.add_argument('right', help="Second member's sketch")
    parser.add_argument('--left-name', default='left')
    parser.add_argument('--right-name', default='right')
    args = parser.parse_args()

    diff = iblt_diff(read_sketch(args.left), read_sketch(args.right))

    if not diff.total and diff.decoded:
        print('Sets are identical.')
        return 0

    for entry in diff.only_in_left:
        print(f'only in {args.left_name}: 0x{entry.hex()}')
    for entry in diff.only_in_right:
        print(f'only in {args.right_name}: 0x{entry.hex()}')

    if not diff.decoded:
        print(
            f'\nWARNING: the sets differ by more than this sketch can resolve. '
            f'The {diff.total} entries above are real but incomplete — compare '
            f"'bucket_counts' from the same log lines to see where the rest are.",
            file=sys.stderr,
        )
        return 2

    print(f'\nRecovered the complete difference: {diff.total} entries.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
