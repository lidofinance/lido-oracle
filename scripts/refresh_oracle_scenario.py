"""Record one accounting scenario and build its portable Layer-2 EL archive."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from record_oracle_scenario_cassette import record

from scripts.network_config import load_network_config


def refresh(
    network_config_path: Path,
    scenario_id: str,
    ref_slot: int,
    historical_ref_slots: list[int],
    cassette_root: Path,
    archive_root: Path,
) -> None:
    network = load_network_config(network_config_path)
    network_name = network.get('network')
    if not isinstance(network_name, str) or not network_name:
        raise ValueError('network config must contain a non-empty network name')

    cassette_path = cassette_root / network_name / scenario_id
    record(
        network_config_path=network_config_path,
        output=cassette_path,
        scenario_id=scenario_id,
        module='accounting',
        ref_slot=ref_slot,
        historical_ref_slots=historical_ref_slots,
    )
    manifest = json.loads((cassette_path / 'manifest.json').read_text(encoding='utf-8'))
    archive_path = archive_root / network_name / f'{manifest["execution_anchor_block"]}.json'
    previous_archive_mtime = archive_path.stat().st_mtime_ns if archive_path.exists() else None

    environment = os.environ.copy()
    environment.update(
        {
            'ORACLE_SCENARIO_NETWORK_CONFIG': str(network_config_path.resolve()),
            'ORACLE_LAYER2_CASSETTE_PATHS': str(cassette_path.resolve()),
            'ORACLE_EL_ARCHIVE_ROOT': str(archive_root.resolve()),
            'UPDATE_ORACLE_EL_ARCHIVES': '1',
        }
    )
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-vv', 'tests/fork/test_glamsterdam_layer2.py'],
        env=environment,
        check=False,
    )
    if not archive_path.exists() or archive_path.stat().st_mtime_ns == previous_archive_mtime:
        raise RuntimeError(f'Layer 2 did not produce a refreshed EL archive at {archive_path}')
    if result.returncode:
        raise SystemExit(
            'The cassette and EL archive were refreshed, but Layer 2 did not match its reviewed golden. '
            'Inspect the report diff, update the golden deliberately, and rerun the offline test.'
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--network-config', type=Path, required=True)
    parser.add_argument('--scenario-id', required=True)
    parser.add_argument('--ref-slot', type=int, required=True)
    parser.add_argument('--historical-ref-slot', type=int, action='append', default=[])
    parser.add_argument('--cassette-root', type=Path, default=Path('tests/cassettes'))
    parser.add_argument('--archive-root', type=Path, default=Path('tests/el-archives'))
    args = parser.parse_args()
    refresh(
        network_config_path=args.network_config,
        scenario_id=args.scenario_id,
        ref_slot=args.ref_slot,
        historical_ref_slots=args.historical_ref_slot,
        cassette_root=args.cassette_root,
        archive_root=args.archive_root,
    )


if __name__ == '__main__':
    main()
