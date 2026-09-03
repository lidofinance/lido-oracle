"""Convert a warmed Foundry fork cache into a self-contained Anvil state archive."""

import argparse
import json
from pathlib import Path
from typing import Any


HEADER_FIELDS = (
    'parentHash',
    'sha3Uncles',
    'miner',
    'stateRoot',
    'transactionsRoot',
    'receiptsRoot',
    'logsBloom',
    'difficulty',
    'number',
    'gasLimit',
    'gasUsed',
    'timestamp',
    'extraData',
    'mixHash',
    'nonce',
    'baseFeePerGas',
    'withdrawalsRoot',
    'blobGasUsed',
    'excessBlobGas',
    'parentBeaconBlockRoot',
    'requestsHash',
)


def build_archive(cache_path: Path, execution_block_path: Path, output: Path) -> None:
    cache = _read_object(cache_path)
    execution_block = _read_object(execution_block_path)
    if 'result' in execution_block:
        result = execution_block['result']
        if not isinstance(result, dict):
            raise ValueError('execution block JSON-RPC result must be an object')
        execution_block = result

    block_number_hex = _required_str(execution_block, 'number')
    block_number = int(block_number_hex, 16)
    block_hash = _required_str(execution_block, 'hash').lower()
    meta = _required_object(cache, 'meta')
    block_env = _required_object(meta, 'block_env')
    if int(_required_str(block_env, 'number'), 16) != block_number:
        raise ValueError('Foundry cache block number does not match execution block')

    block_hashes = _required_object(cache, 'block_hashes')
    cached_hash = block_hashes.get(block_number_hex.lower())
    if not isinstance(cached_hash, str) or cached_hash.lower() != block_hash:
        raise ValueError('Foundry cache does not contain the expected execution anchor hash')

    cached_accounts = _required_object(cache, 'accounts')
    cached_storage = _required_object(cache, 'storage')
    addresses = set(cached_accounts) | set(cached_storage)
    accounts: dict[str, object] = {}
    for address in sorted(addresses):
        account = cached_accounts.get(address, {})
        storage = cached_storage.get(address, {})
        if not isinstance(account, dict) or not isinstance(storage, dict):
            raise ValueError(f'invalid Foundry cache account {address!r}')
        accounts[address] = {
            'nonce': account.get('nonce', 0),
            'balance': account.get('balance', '0x0'),
            'code': _extract_bytecode(account.get('code')),
            'storage': storage,
        }

    header = {key: execution_block[key] for key in HEADER_FIELDS if key in execution_block}
    archive = {
        'block': block_env,
        'accounts': accounts,
        'best_block_number': block_number,
        'blocks': [{'header': header, 'transactions': [], 'ommers': []}],
        'transactions': [],
        'historical_states': None,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(archive, separators=(',', ':')) + '\n', encoding='utf-8')
    output.with_suffix('.block.json').write_text(
        json.dumps(execution_block, separators=(',', ':')) + '\n', encoding='utf-8'
    )


def _extract_bytecode(value: object) -> str:
    if value is None:
        return '0x'
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for analyzed in value.values():
            if isinstance(analyzed, dict) and isinstance(analyzed.get('bytecode'), str):
                if analyzed.get('original_len') == 0:
                    return '0x'
                return analyzed['bytecode']
    raise ValueError('unsupported Foundry cached bytecode representation')


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError as error:
        raise ValueError(f'missing JSON file: {path}') from error
    if not isinstance(value, dict):
        raise ValueError(f'JSON file must contain an object: {path}')
    return value


def _required_object(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise ValueError(f'field {key!r} must be an object')
    return item


def _required_str(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f'field {key!r} must be a non-empty string')
    return item


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--foundry-cache', type=Path, required=True)
    parser.add_argument('--execution-block', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build_archive(args.foundry_cache, args.execution_block, args.output)


if __name__ == '__main__':
    main()
