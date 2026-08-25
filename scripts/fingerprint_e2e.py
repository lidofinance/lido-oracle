#!/usr/bin/env python3
"""Check the response fingerprints against live providers, and capture test fixtures.

Two things worth checking against real data, neither of which a unit test can:

- **agreement** — two independent consensus nodes handed the same slot must produce the
  same digest. If they do not, the fingerprint cannot be compared between members and the
  whole diagnostic is worthless. Point `--cl` at two hosts that both have the slot; a
  lagging node will silently serve its own head state instead, which shows up as a
  differing `slot` in the output rather than as a mystery.
- **cost** — the digest is pure Python over the whole response, so it is worth re-measuring
  as mainnet grows.

    scripts/fingerprint_e2e.py \\
        --cl http://node-a http://node-b \\
        --kapi https://keys-api.lido.fi \\
        --slot 14921600 --out /tmp/fp

`--out` receives the trimmed slices used by `tests/utils/test_fingerprint_mainnet_fixtures.py`.
Regenerating those changes the pinned digests, which is a breaking change for anyone
comparing against a running release — do it only alongside a deliberate encoding change.
"""

import argparse
import gc
import json
import logging
import pathlib
import sys
import time

from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.types import BeaconStateView
from src.providers.keys.client import KeysAPIClient
from src.types import BlockStamp
from src.utils.fingerprint import digest_of


logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr)
logger = logging.getLogger('fingerprint-e2e')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--cl', nargs='*', default=[], metavar='HOST', help='consensus nodes to compare')
    parser.add_argument('--kapi', metavar='HOST', help='Keys API host')
    parser.add_argument('--slot', type=int, help='slot to fetch; defaults to finalized on the first --cl host')
    parser.add_argument('--out', type=pathlib.Path, help='write fixture slices here')
    parser.add_argument('--slice', type=int, default=100, help='entries per list in the fixtures')
    args = parser.parse_args()

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    report: dict = {}
    if args.kapi:
        report['kapi'] = _kapi(args)
    if args.cl:
        report['cl'] = _cl(args)

    print(json.dumps(report, indent=2))
    agreed = all(section['agree'] for section in report.values())
    return 0 if agreed else 1


def _kapi(args) -> dict:
    client = KeysAPIClient([args.kapi], 5 * 60, 3, 5)
    status, _ = client._get('v1/status')  # noqa: SLF001
    snapshot = status['elBlockSnapshot']
    blockstamp = BlockStamp(
        state_root='',
        slot_number=0,
        block_hash=snapshot['blockHash'],
        block_number=snapshot['blockNumber'],
        block_timestamp=snapshot['timestamp'],
    )

    keys, fetch_s = _timed('keys api fetch', lambda: client.get_used_lido_keys(blockstamp))
    digest, digest_s = _timed('keys api digest', lambda: digest_of(keys))
    _write(args, 'mainnet_kapi_used_keys_slice.json', [vars(key) for key in keys[: args.slice]])

    # A second call: the Keys API promises no row order, so this is where a digest that is
    # sensitive to it would show up as a spurious difference.
    again, _ = _timed(
        'keys api fetch (again)', lambda: KeysAPIClient([args.kapi], 5 * 60, 3, 5).get_used_lido_keys(blockstamp)
    )
    repeat = digest_of(again)

    return {
        'host': args.kapi,
        'digest': digest,
        'repeat_digest': repeat,
        'count': len(keys),
        'el_block_number': snapshot['blockNumber'],
        'fetch_s': round(fetch_s, 1),
        'digest_s': round(digest_s, 1),
        'agree': digest == repeat,
    }


def _cl(args) -> dict:
    slot = args.slot
    if slot is None:
        anchor = ConsensusClient([args.cl[0]], 60, 3, 5)
        slot = anchor.get_block_details(anchor.get_block_root('finalized').root).message.slot
        logger.info('finalized slot %s', slot)

    runs = []
    for index, host in enumerate(args.cl):
        client = ConsensusClient([host], 15 * 60, 3, 5)
        state, fetch_s = _timed(
            f'state fetch {host}',
            lambda c=client: BeaconStateView.from_response(**c._get_state_by_state_id(slot)),  # noqa: SLF001
        )
        digest, digest_s = _timed(f'state digest {host}', lambda s=state: digest_of(s))
        runs.append(
            {
                'host': host,
                'digest': digest,
                # A node behind the requested slot may serve its own head instead: compare.
                'slot': state.slot,
                'validators': len(state.validators),
                'pending_deposits': len(state.pending_deposits),
                'fetch_s': round(fetch_s, 1),
                'digest_s': round(digest_s, 1),
            }
        )
        if index == 0:
            _write(args, 'mainnet_beacon_state_slice.json', _slice(state, args.slice))
        del state
        gc.collect()

    return {'requested_slot': slot, 'runs': runs, 'agree': len({run['digest'] for run in runs}) == 1}


def _slice(state: BeaconStateView, size: int) -> dict:
    """Verbatim provider values, truncated. Nothing is rewritten."""
    return {
        'slot': state.slot,
        'validators': [vars(v) for v in state.validators[:size]],
        'balances': list(state.balances[:size]),
        'slashings': list(state.slashings),
        'exit_balance_to_consume': state.exit_balance_to_consume,
        'earliest_exit_epoch': state.earliest_exit_epoch,
        'pending_deposits': [vars(d) for d in state.pending_deposits[:size]],
        'pending_partial_withdrawals': [vars(w) for w in state.pending_partial_withdrawals],
        'pending_consolidations': [vars(c) for c in state.pending_consolidations],
    }


def _timed(label, fn):
    started = time.monotonic()
    result = fn()
    elapsed = time.monotonic() - started
    logger.info('%-46s %6.1f s', label, elapsed)
    return result, elapsed


def _write(args, name: str, payload) -> None:
    if not args.out:
        return
    path = args.out / name
    with open(path, 'w') as fd:
        json.dump(payload, fd, indent=2)
        fd.write('\n')
    logger.info('%-46s %6.0f KB', f'wrote {name}', path.stat().st_size / 1024)


if __name__ == '__main__':
    sys.exit(main())
