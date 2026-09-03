"""Find finalized devnet frames that are useful as oracle scenario cassettes."""

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

import requests
from eth_typing import ChecksumAddress, HexStr
from web3 import Web3

from scripts.network_config import load_network_config, network_endpoint


@dataclass(frozen=True)
class ScanResult:
    ref_slot: int
    child_slot: int | None
    status: str
    payload_confirmed: bool | None = None
    missed_child_slots: int = 0
    expected_withdrawals: int = 0
    expected_withdrawals_gwei: int = 0
    lido_expected_withdrawals: int = 0
    lido_expected_withdrawals_gwei: int = 0
    new_pending_deposits: int = 0
    new_lido_pending_deposits: int = 0
    pending_partial_withdrawals: int = 0
    slashed_lido_validators: int = 0
    unfinalized_steth_wei: int | None = None
    liquid_el_wei: int | None = None
    candidates: tuple[str, ...] = ()
    error: str | None = None


def get_json(session: requests.Session, url: str, *, allow_not_found: bool = False) -> dict[str, Any] | None:
    response = session.get(url, timeout=120)
    if allow_not_found and response.status_code == 404:
        return None
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError(f'expected JSON object from {url}')
    return value


def find_header(
    session: requests.Session, cl_url: str, start_slot: int, finalized_slot: int
) -> tuple[int, dict[str, Any]]:
    for slot in range(start_slot, finalized_slot + 1):
        header = get_json(session, f'{cl_url}/eth/v1/beacon/headers/{slot}', allow_not_found=True)
        if header is not None:
            return slot, header
    raise ValueError(f'no block found from slot {start_slot} through finalized slot {finalized_slot}')


def load_abi(path: str) -> list[dict[str, Any]]:
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, list):
        raise ValueError(f'ABI must be a JSON array: {path}')
    return value


def normalized_items(values: list[dict[str, Any]]) -> Counter[str]:
    return Counter(json.dumps(value, sort_keys=True, separators=(',', ':')) for value in values)


def scan_frame(  # noqa: C901 - one frame intentionally collects all cross-layer candidate signals
    session: requests.Session,
    web3: Web3,
    cl_url: str,
    finalized_slot: int,
    ref_slot: int,
    lido_keys: set[str],
    withdrawal_queue_address: ChecksumAddress,
    withdrawal_vault_address: ChecksumAddress,
    el_rewards_vault_address: ChecksumAddress,
    lido_address: ChecksumAddress,
) -> ScanResult:
    try:
        parent_header = get_json(
            session,
            f'{cl_url}/eth/v1/beacon/headers/{ref_slot}',
            allow_not_found=True,
        )
        ref_slot_missed = parent_header is None
        if parent_header is None:
            child_slot, child_header = find_header(session, cl_url, ref_slot + 1, finalized_slot)
            parent_root = child_header['data']['header']['message']['parent_root']
            parent_header = get_json(session, f'{cl_url}/eth/v1/beacon/headers/{parent_root}')
            if parent_header is None:
                raise ValueError(f'parent header {parent_root} was not found')
        else:
            child_slot, child_header = find_header(session, cl_url, ref_slot + 1, finalized_slot)
        parent_root = parent_header['data']['root']
        parent_state_root = parent_header['data']['header']['message']['state_root']
        child_state_root = child_header['data']['header']['message']['state_root']
        parent_block = get_json(session, f'{cl_url}/eth/v2/beacon/blocks/{parent_root}')
        parent_state_response = get_json(session, f'{cl_url}/eth/v2/debug/beacon/states/{parent_state_root}')
        child_state_response = get_json(session, f'{cl_url}/eth/v2/debug/beacon/states/{child_state_root}')
        assert parent_block is not None and parent_state_response is not None and child_state_response is not None
        parent_state = parent_state_response['data']
        child_state = child_state_response['data']

        bid = parent_block['data']['message']['body'].get('signed_execution_payload_bid')
        bid_hash = bid['message']['block_hash'] if bid is not None else None
        anchor_hash = child_state.get('latest_block_hash')
        payload_confirmed = bool(bid_hash and anchor_hash and bid_hash.lower() == anchor_hash.lower())

        validators = parent_state.get('validators', [])
        lido_indices = {index for index, validator in enumerate(validators) if validator['pubkey'].lower() in lido_keys}
        expected = parent_state.get('payload_expected_withdrawals', [])
        lido_expected = [item for item in expected if int(item['validator_index']) in lido_indices]

        parent_pending = parent_state.get('pending_deposits', [])
        child_pending = child_state.get('pending_deposits', [])
        new_pending_values = normalized_items(child_pending) - normalized_items(parent_pending)
        new_pending = [json.loads(value) for value in new_pending_values.elements()]
        new_lido_pending = [item for item in new_pending if item.get('pubkey', '').lower() in lido_keys]

        slashed_lido = sum(
            validator['slashed'] is True for index, validator in enumerate(validators) if index in lido_indices
        )
        partials = parent_state.get('pending_partial_withdrawals', [])

        unfinalized_steth: int | None = None
        liquid_el: int | None = None
        if isinstance(anchor_hash, str) and anchor_hash:
            block_identifier = HexStr(anchor_hash)
            withdrawal_queue = web3.eth.contract(
                address=Web3.to_checksum_address(withdrawal_queue_address),
                abi=load_abi('assets/WithdrawalQueueERC721.json'),
            )
            lido = web3.eth.contract(
                address=Web3.to_checksum_address(lido_address),
                abi=load_abi('assets/Lido.json'),
            )
            unfinalized_steth = withdrawal_queue.functions.unfinalizedStETH().call(block_identifier=block_identifier)
            liquid_el = (
                web3.eth.get_balance(withdrawal_vault_address, block_identifier=block_identifier)
                + web3.eth.get_balance(el_rewards_vault_address, block_identifier=block_identifier)
                + lido.functions.getBufferedEther().call(block_identifier=block_identifier)
            )

        candidates: list[str] = []
        if ref_slot_missed:
            candidates.append('AC-10-missed-ref-slot')
        elif child_slot > ref_slot + 1:
            candidates.append('AC-10-missed-child')
        if not payload_confirmed:
            candidates.append('AC-02')
        if not payload_confirmed and lido_expected:
            candidates.append('AC-02-with-lido-withdrawals')
        if payload_confirmed and new_lido_pending:
            candidates.append('AC-08')
        if slashed_lido:
            candidates.append('AC-05-signal')
        if unfinalized_steth is not None and liquid_el is not None and unfinalized_steth > liquid_el:
            candidates.extend(('EJ-01', 'EJ-03'))
        if partials:
            candidates.append('EJ-04-signal')

        return ScanResult(
            ref_slot=ref_slot,
            child_slot=child_slot,
            status='ref_slot_missed_resolved' if ref_slot_missed else 'ok',
            payload_confirmed=payload_confirmed,
            missed_child_slots=child_slot - ref_slot - 1,
            expected_withdrawals=len(expected),
            expected_withdrawals_gwei=sum(int(item['amount']) for item in expected),
            lido_expected_withdrawals=len(lido_expected),
            lido_expected_withdrawals_gwei=sum(int(item['amount']) for item in lido_expected),
            new_pending_deposits=len(new_pending),
            new_lido_pending_deposits=len(new_lido_pending),
            pending_partial_withdrawals=len(partials),
            slashed_lido_validators=slashed_lido,
            unfinalized_steth_wei=unfinalized_steth,
            liquid_el_wei=liquid_el,
            candidates=tuple(candidates),
        )
    except Exception as error:  # noqa: BLE001 - a scan should report inaccessible historical frames and continue
        return ScanResult(ref_slot, None, 'error', error=f'{type(error).__name__}: {error}')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--network-config', type=Path, required=True)
    parser.add_argument('--frames', type=int, default=24)
    parser.add_argument('--ref-slot', type=int, action='append', default=[])
    parser.add_argument('--include-empty', action='store_true')
    args = parser.parse_args()

    network = load_network_config(args.network_config)
    cl_url = network_endpoint(network, 'consensus').rstrip('/')
    web3 = Web3(Web3.HTTPProvider(network_endpoint(network, 'execution'), request_kwargs={'timeout': 120}))
    contracts = network['contracts']
    hash_consensus = web3.eth.contract(
        address=Web3.to_checksum_address(contracts['hash_consensus_accounting']),
        abi=load_abi('assets/HashConsensus.json'),
    )
    locator = web3.eth.contract(
        address=Web3.to_checksum_address(contracts['lido_locator']),
        abi=load_abi('assets/LidoLocator.json'),
    )

    session = requests.Session()
    finalized = get_json(session, f'{cl_url}/eth/v1/beacon/headers/finalized')
    keys_url = network_endpoint(network, 'keys_api').rstrip('/')
    keys_response = get_json(session, f'{keys_url}/v1/keys?used=true')
    assert finalized is not None and keys_response is not None
    finalized_slot = int(finalized['data']['header']['message']['slot'])
    lido_keys = {item['key'].lower() for item in keys_response['data']}

    current_ref_slot = int(hash_consensus.functions.getCurrentFrame().call()[0])
    initial_ref_slot = int(hash_consensus.functions.getInitialRefSlot().call())
    frame_config = hash_consensus.functions.getFrameConfig().call()
    slots_per_epoch = int(hash_consensus.functions.getChainConfig().call()[0])
    frame_slots = int(frame_config[1]) * slots_per_epoch
    first_ref_slot = min(current_ref_slot, finalized_slot - 1)
    first_ref_slot -= (first_ref_slot - initial_ref_slot) % frame_slots
    if args.ref_slot:
        ref_slots = args.ref_slot
    else:
        ref_slots = [first_ref_slot - index * frame_slots for index in range(args.frames)]
        ref_slots = [slot for slot in ref_slots if slot >= initial_ref_slot]

    results = [
        scan_frame(
            session=session,
            web3=web3,
            cl_url=cl_url,
            finalized_slot=finalized_slot,
            ref_slot=ref_slot,
            lido_keys=lido_keys,
            withdrawal_queue_address=cast(ChecksumAddress, locator.functions.withdrawalQueue().call()),
            withdrawal_vault_address=cast(ChecksumAddress, locator.functions.withdrawalVault().call()),
            el_rewards_vault_address=cast(ChecksumAddress, locator.functions.elRewardsVault().call()),
            lido_address=Web3.to_checksum_address(contracts['lido']),
        )
        for ref_slot in ref_slots
    ]
    output = {
        'network': network['network'],
        'finalized_slot': finalized_slot,
        'current_ref_slot': current_ref_slot,
        'frame_slots': frame_slots,
        'frames_scanned': len(results),
        'matches': [asdict(result) for result in results if result.candidates],
        'frames': [asdict(result) for result in results] if args.include_empty else [],
    }
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
