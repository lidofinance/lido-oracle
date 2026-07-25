#!/usr/bin/env python3
"""Recover the exact entries two oracle members disagreed about, from their logs.

Each member logs an IBLT sketch of every large input it built its report from — the Keys
API used-key set, the pending deposit queue, the selected pending validators. Subtracting
two sketches and peeling them yields the full symmetric difference: every key or deposit
one member had and the other did not, and which side was missing it. No key data has to be
exchanged between operators; the two log lines are enough.

Usage:

    # pull the sketch out of each member's log for the same reference slot
    grep '"msg": "Used Lido keys sketch."' member-a.log | tail -1 > a.json
    grep '"msg": "Used Lido keys sketch."' member-b.log | tail -1 > b.json

    python3 scripts/reconcile_fingerprints.py a.json b.json

Accepts either the whole JSON log line or a bare 0x sketch, as a file or inline.
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
    if os.path.exists(source):
        with open(source) as handle:
            raw = handle.read().strip()
    else:
        raw = source.strip()

    if raw.startswith('0x'):
        return raw

    line = json.loads(raw)
    if 'iblt' not in line:
        raise SystemExit(f"No 'iblt' field in {source} — is this a '<subject> sketch.' log line?")
    return line['iblt']


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
