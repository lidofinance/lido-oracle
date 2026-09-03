"""Record CL/KAPI responses for an already-finalized oracle reference slot."""

import argparse
import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from scripts.network_config import load_network_config, network_endpoint


SCHEMA_VERSION = 1


def request_json(session: requests.Session, url: str) -> dict[str, Any]:
    response = session.get(url, timeout=120)
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError(f'expected JSON object from {url}')
    return value


def rpc_json(session: requests.Session, url: str, method: str, params: list[object]) -> Any:
    response = session.post(
        url,
        json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params},
        timeout=120,
    )
    response.raise_for_status()
    value = response.json()
    if 'error' in value:
        raise ValueError(f'JSON-RPC {method} failed: {value["error"]!r}')
    return value.get('result')


def find_header(session: requests.Session, cl_url: str, start_slot: int, stop_slot: int) -> dict[str, Any]:
    for slot in range(start_slot, stop_slot + 1):
        response = session.get(f'{cl_url}/eth/v1/beacon/headers/{slot}', timeout=30)
        if response.status_code == 404:
            continue
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError(f'expected header object for slot {slot}')
        return value
    raise ValueError(f'no block found in slot range [{start_slot}, {stop_slot}]')


def resolve_execution_anchor(parent_block: dict[str, Any], child_state: dict[str, Any]) -> tuple[str, str]:
    """Resolve the EL anchor hash the oracle would use, and name the branch it came from.

    Mirrors `blockstamp._resolve_anchor_block`, which selects on block *shape* rather than
    on the spec's fork epoch: a pre-fork body embeds its own `execution_payload`, a Gloas body does
    not and the anchor moves to the child state's `latest_block_hash`. Recording the wrong branch
    would bake a post-fork assumption into a pre-fork cassette, so keep the two in step.
    """
    payload = parent_block['data']['message']['body'].get('execution_payload')
    if payload is not None:
        return payload['block_hash'], 'pre_fork_embedded_payload'

    anchor_hash = child_state['data'].get('latest_block_hash')
    if not anchor_hash:
        raise ValueError(
            'block carries no execution_payload and the child state has no latest_block_hash: '
            'cannot resolve an execution anchor'
        )
    return anchor_hash, 'gloas_child_state_latest_block_hash'


def write_gzip_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, 'wt', encoding='utf-8') as output:
        json.dump(value, output, separators=(',', ':'))


def record(
    network_config_path: Path,
    output: Path,
    scenario_id: str,
    module: str,
    ref_slot: int,
    historical_ref_slots: list[int],
) -> None:
    network_config = load_network_config(network_config_path)
    el_url = network_endpoint(network_config, 'execution').rstrip('/')
    cl_url = network_endpoint(network_config, 'consensus').rstrip('/')
    kapi_url = network_endpoint(network_config, 'keys_api').rstrip('/')

    session = requests.Session()
    spec = request_json(session, f'{cl_url}/eth/v1/config/spec')
    genesis = request_json(session, f'{cl_url}/eth/v1/beacon/genesis')
    finalized = request_json(session, f'{cl_url}/eth/v1/beacon/headers/finalized')
    finalized_slot = int(finalized['data']['header']['message']['slot'])
    if ref_slot >= finalized_slot:
        raise ValueError(f'ref slot {ref_slot} needs a finalized child; finalized slot is only {finalized_slot}')

    output.mkdir(parents=True, exist_ok=True)
    responses: list[dict[str, object]] = [
        {'provider': 'consensus', 'method': 'get_config_spec', 'params': {}, 'response': spec},
        {'provider': 'consensus', 'method': 'get_genesis', 'params': {}, 'response': genesis},
    ]
    checkpoint_metadata: dict[int, dict[str, object]] = {}

    for checkpoint_slot in [ref_slot, *historical_ref_slots]:
        parent_header = find_header(session, cl_url, checkpoint_slot, finalized_slot)
        parent_slot = int(parent_header['data']['header']['message']['slot'])
        if parent_slot != checkpoint_slot:
            raise ValueError(
                'recorder currently requires a non-missed ref slot; '
                f'requested {checkpoint_slot}, first block is {parent_slot}'
            )
        child_header = find_header(session, cl_url, parent_slot + 1, finalized_slot)
        child_slot = int(child_header['data']['header']['message']['slot'])
        parent_root = parent_header['data']['root']
        child_root = child_header['data']['root']
        parent_state_root = parent_header['data']['header']['message']['state_root']
        child_state_root = child_header['data']['header']['message']['state_root']

        parent_block = request_json(session, f'{cl_url}/eth/v2/beacon/blocks/{parent_root}')
        child_block = request_json(session, f'{cl_url}/eth/v2/beacon/blocks/{child_root}')
        parent_state = request_json(session, f'{cl_url}/eth/v2/debug/beacon/states/{parent_state_root}')
        child_state = request_json(session, f'{cl_url}/eth/v2/debug/beacon/states/{child_state_root}')
        execution_anchor_hash, anchor_branch = resolve_execution_anchor(parent_block, child_state)
        execution_anchor_block = rpc_json(session, el_url, 'eth_getBlockByHash', [execution_anchor_hash, False])
        if not isinstance(execution_anchor_block, dict):
            raise ValueError(f'execution anchor block {execution_anchor_hash} was not found')

        parent_state_file = f'responses/state-{parent_slot}.json.gz'
        child_state_file = f'responses/state-{child_slot}.json.gz'
        write_gzip_json(output / parent_state_file, parent_state)
        write_gzip_json(output / child_state_file, child_state)
        responses.extend(
            [
                {
                    'provider': 'consensus',
                    'method': 'get_block_header',
                    'params': {'state_id': str(checkpoint_slot)},
                    'response': parent_header,
                },
                {
                    'provider': 'consensus',
                    'method': 'get_block_header',
                    'params': {'state_id': str(child_slot)},
                    'response': child_header,
                },
                {
                    'provider': 'consensus',
                    'method': 'get_block_details',
                    'params': {'state_id': parent_root},
                    'response': parent_block,
                },
                {
                    'provider': 'consensus',
                    'method': 'get_block_details',
                    'params': {'state_id': child_root},
                    'response': child_block,
                },
                {
                    'provider': 'consensus',
                    'method': 'get_state_view',
                    'params': {'state_root': parent_state_root, 'slot_number': parent_slot},
                    'response_file': parent_state_file,
                },
                {
                    'provider': 'consensus',
                    'method': 'get_state_view',
                    'params': {'state_root': child_state_root, 'slot_number': child_slot},
                    'response_file': child_state_file,
                },
                {
                    'provider': 'execution',
                    'method': 'get_block',
                    'params': {'block_hash': execution_anchor_hash},
                    'response': execution_anchor_block,
                },
            ]
        )
        for missed_slot in range(parent_slot + 1, child_slot):
            responses.append(
                {
                    'provider': 'consensus',
                    'method': 'get_block_header',
                    'params': {'state_id': str(missed_slot)},
                    'response': {'cassette_http_status': 404},
                }
            )
        checkpoint_metadata[checkpoint_slot] = {
            'resolved_slot': parent_slot,
            'child_slot': child_slot,
            'execution_anchor_branch': anchor_branch,
            'execution_anchor_hash': execution_anchor_hash,
            'execution_anchor_block': int(execution_anchor_block['number'], 16),
            'execution_anchor_timestamp': int(execution_anchor_block['timestamp'], 16),
        }

    used_keys = request_json(session, f'{kapi_url}/v1/keys?used=true')
    write_gzip_json(output / 'responses/used-keys.json.gz', used_keys)
    responses.append(
        {
            'provider': 'keys_api',
            'method': 'get_used_lido_keys',
            'params': {},
            'response_file': 'responses/used-keys.json.gz',
        }
    )
    manifest = {
        'schema_version': SCHEMA_VERSION,
        'scenario_id': scenario_id,
        'network': network_config['network'],
        'module': module,
        'ref_slot': ref_slot,
        'recorded_at': datetime.now(UTC).isoformat(),
        'consensus_spec': spec['data'],
        'chain_id': network_config['chain_id'],
        'contracts': network_config['contracts'],
        **checkpoint_metadata[ref_slot],
        'historical_ref_slots': historical_ref_slots,
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    (output / 'responses.json').write_text(json.dumps(responses, indent=2) + '\n', encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--network-config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scenario-id', required=True)
    parser.add_argument('--module', choices=('accounting', 'ejector'), required=True)
    parser.add_argument('--ref-slot', type=int, required=True)
    parser.add_argument('--historical-ref-slot', type=int, action='append', default=[])
    args = parser.parse_args()
    record(
        args.network_config,
        args.output,
        args.scenario_id,
        args.module,
        args.ref_slot,
        args.historical_ref_slot,
    )


if __name__ == '__main__':
    main()
