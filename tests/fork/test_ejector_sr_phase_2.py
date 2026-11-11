"""
The ejector against the SR phase 2 (LIP-38) contracts, deployed and enacted on a mainnet fork.

Needs a lidofinance/core checkout with the SR phase 2 upgrade scripts in `LIDO_CORE_PATH`,
with its dependencies installed and contracts compiled.
"""

import json
import logging
import os
import subprocess
from pathlib import Path

import pytest
from eth_typing import HexStr
from web3.types import RPCEndpoint, TxParams, TxReceipt

from src.modules.common.types import FrameConfig
from src.modules.oracles.ejector.data_encode import WithdrawalRequest
from src.modules.oracles.ejector.ejector import Ejector
from src.types import ReferenceBlockStamp
from src.utils.range import sequence
from tests.fork.conftest import first_slot_of_epoch


logger = logging.getLogger('fork_tests')

WSTETH = '0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0'
DEPLOYER = '0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266'
# EIP-7825 transaction gas cap
TX_GAS_LIMIT = 2**24
# A report at the 11,520 ETH limit set by the vote, 360 FWRs, needs ~27M gas: more than the EIP-7825 cap.
# 3,200 ETH is 100 FWRs, which fits.
REPORT_BALANCE_LIMIT_ETH = 3_200
# Large enough that the predicted EL balance cannot cover it, so phase 1 has to request withdrawals.
WITHDRAWAL_DEMAND_STETH = 200_000 * 10**18
MAX_STETH_PER_WITHDRAWAL_REQUEST = 1_000 * 10**18

VOTE_SCRIPT_ABI = [
    {
        'name': name,
        'type': 'function',
        'stateMutability': 'view',
        'inputs': [],
        'outputs': [
            {
                'name': 'items',
                'type': 'tuple[]',
                'components': [
                    {'name': 'description', 'type': 'string'},
                    {
                        'name': 'call',
                        'type': 'tuple',
                        'components': [{'name': 'to', 'type': 'address'}, {'name': 'data', 'type': 'bytes'}],
                    },
                ],
            }
        ],
    }
    for name in ('getVotingVoteItems', 'getVoteItems')
]
BATCH_EXECUTOR_PATH = Path('tests/fork/contracts/sr_phase_2')
BATCH_EXECUTOR_ABI = [
    {
        'name': 'run',
        'type': 'function',
        'stateMutability': 'nonpayable',
        'inputs': [
            {'name': 'executor', 'type': 'address'},
            {'name': 'targets', 'type': 'address[]'},
            {'name': 'payloads', 'type': 'bytes[]'},
            {'name': 'owner', 'type': 'address'},
        ],
        'outputs': [],
    }
]
EXECUTOR_ABI = [
    {
        'name': 'transferOwnership',
        'type': 'function',
        'stateMutability': 'nonpayable',
        'inputs': [{'name': 'newOwner', 'type': 'address'}],
        'outputs': [],
    },
    {
        'name': 'owner',
        'type': 'function',
        'stateMutability': 'view',
        'inputs': [],
        'outputs': [{'name': '', 'type': 'address'}],
    },
]
TIMELOCK_ABI = [
    {
        'name': 'getAdminExecutor',
        'type': 'function',
        'stateMutability': 'view',
        'inputs': [],
        'outputs': [{'name': '', 'type': 'address'}],
    }
]


@pytest.fixture()
def core_path() -> Path:
    path = os.getenv('LIDO_CORE_PATH')
    if not path:
        pytest.skip('LIDO_CORE_PATH is not set')
    return Path(path)


def _deploy_sr_phase_2(core_path: Path, rpc_url: str) -> dict:
    # The migration copies the mainnet state into these files and reuses them if they exist.
    for leftover in ('deployed-local.json', 'scripts/upgrade/upgrade-params-local.toml'):
        (core_path / leftover).unlink(missing_ok=True)

    env = {
        **os.environ,
        'NETWORK': 'mainnet',
        'RUN_NETWORK': 'local',
        'RPC_URL': rpc_url,
        'MODE': 'forking',
        'UPGRADE': 'true',
        'AUTO_CONFIRM': 'true',
        'STEPS_FILE': 'upgrade/steps-sr-phase-2-upgrade.json',
        'DEPLOYER': DEPLOYER,
        'GAS_PRIORITY_FEE': '1',
        'GAS_MAX_FEE': '100',
        'SKIP_INTERFACES_CHECK': 'true',
        'SKIP_CONTRACT_SIZE': 'true',
        'SKIP_GAS_REPORT': 'true',
        'SKIP_LINT_SOLIDITY': 'true',
    }
    result = subprocess.run(
        ['bash', 'scripts/run-migration.sh'],
        cwd=core_path,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    logger.info(f'TESTRUN SR phase 2 deployment output:\n{result.stdout[-5000:]}')
    assert result.returncode == 0, result.stderr[-5000:]

    with open(core_path / 'deployed-local.json') as f:
        state = json.load(f)
    assert 'srPhase2UpgradeVoteScript' in state, 'The SR phase 2 vote script was not deployed'
    return state


def _send(w3, sender: str, to: str | None, data: HexStr | bytes) -> TxReceipt:
    w3.provider.make_request(RPCEndpoint('anvil_setBalance'), [sender, hex(10**20)])
    tx = TxParams({'from': sender, 'data': data, 'gas': TX_GAS_LIMIT})
    if to is not None:
        tx['to'] = to
    receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_transaction(tx))
    assert receipt['status'] == 1, f'Transaction to {to} reverted'
    return receipt


def _enact_sr_phase_2(w3, state: dict) -> None:
    """
    Executes the vote items as the Aragon Voting and the Dual Governance timelock would, without moving
    the chain time: it has to stay on the real CL slots, and the timelock delays are days long.
    The timelock runs all proposal calls in one transaction, and the upgrade template relies on it, so
    the batch executor takes over the admin executor for that one transaction.
    """
    vote_script = w3.eth.contract(address=state['srPhase2UpgradeVoteScript']['address'], abi=VOTE_SCRIPT_ABI)
    voting = state['app:aragon-voting']['proxy']['address']
    timelock_address = state['dg:emergencyProtectedTimelock']['proxy']['address']
    timelock = w3.eth.contract(address=timelock_address, abi=TIMELOCK_ABI)
    admin_executor = w3.eth.contract(address=timelock.functions.getAdminExecutor().call(), abi=EXECUTOR_ABI)

    for description, (to, data) in vote_script.functions.getVotingVoteItems().call():
        logger.info(f'TESTRUN Execute vote item: {description}')
        _send(w3, voting, to, data)

    batch_executor = w3.eth.contract(
        address=_send(w3, DEPLOYER, None, HexStr((BATCH_EXECUTOR_PATH / 'BatchExecutor_bin').read_text().strip()))[
            'contractAddress'
        ],
        abi=BATCH_EXECUTOR_ABI,
    )
    _send(
        w3,
        timelock_address,
        admin_executor.address,
        admin_executor.encode_abi('transferOwnership', [batch_executor.address]),
    )
    items = vote_script.functions.getVoteItems().call()
    for description, _ in items:
        logger.info(f'TESTRUN Execute DG proposal item: {description}')
    _send(
        w3,
        DEPLOYER,
        batch_executor.address,
        batch_executor.encode_abi(
            'run',
            [admin_executor.address, [to for _, (to, _) in items], [data for _, (_, data) in items], timelock_address],
        ),
    )
    assert admin_executor.functions.owner().call() == timelock_address


@pytest.fixture()
def sr_phase_2_upgraded(forked_el_client, anvil_port, core_path):
    state = _deploy_sr_phase_2(core_path, f'http://127.0.0.1:{anvil_port}')
    _enact_sr_phase_2(forked_el_client, state)


@pytest.fixture()
def web3(sr_phase_2_upgraded, web3):
    """The oracle loads the contracts through the locator, so it has to start after the upgrade."""
    return web3


@pytest.fixture()
def withdrawal_demand(web3, accounts_from_fork):
    addresses, _ = accounts_from_fork
    requester = addresses[-1]
    lido = web3.lido_contracts.lido
    withdrawal_queue = web3.lido_contracts.withdrawal_queue_nft

    web3.provider.make_request(RPCEndpoint('anvil_setBalance'), [WSTETH, hex(10**18)])
    lido.functions.transfer(requester, WITHDRAWAL_DEMAND_STETH).transact({'from': WSTETH})
    lido.functions.approve(withdrawal_queue.address, WITHDRAWAL_DEMAND_STETH).transact({'from': requester})
    amounts = [MAX_STETH_PER_WITHDRAWAL_REQUEST] * (WITHDRAWAL_DEMAND_STETH // MAX_STETH_PER_WITHDRAWAL_REQUEST)
    withdrawal_queue.functions.requestWithdrawals(amounts, requester).transact({'from': requester})


@pytest.fixture()
def report_balance_limit(web3):
    checker = web3.lido_contracts.oracle_report_sanity_checker
    admin = checker.functions.getRoleMember(checker.functions.DEFAULT_ADMIN_ROLE().call(), 0).call()
    role = checker.functions.MAX_BALANCE_EXIT_REQUESTED_PER_REPORT_IN_ETH_ROLE().call()
    _send(web3, admin, checker.address, checker.encode_abi('grantRole', [role, admin]))
    _send(
        web3,
        admin,
        checker.address,
        checker.encode_abi('setMaxBalanceExitRequestedPerReportInEth', [REPORT_BALANCE_LIMIT_ETH]),
    )


@pytest.fixture()
def hash_consensus_bin():
    with open('tests/fork/contracts/lido/HashConsensus_bin') as f:
        yield f.read()


@pytest.fixture
def ejector_module(web3, monkeypatch):
    # The contracts may set another consensus version than the oracle expects; the format is what is tested here.
    consensus_version = web3.lido_contracts.validators_exit_bus_oracle.get_consensus_version('latest')
    monkeypatch.setattr(Ejector, 'COMPATIBLE_CONSENSUS_VERSION', consensus_version)
    yield Ejector(web3)


@pytest.fixture
def start_before_initial_epoch(frame_config: FrameConfig):
    return [first_slot_of_epoch(i) for i in sequence(frame_config.initial_epoch - 1, frame_config.initial_epoch + 2)]


@pytest.fixture
def reported_requests(monkeypatch) -> list[tuple[ReferenceBlockStamp, list[WithdrawalRequest]]]:
    reports: list[tuple[ReferenceBlockStamp, list[WithdrawalRequest]]] = []
    get_withdrawal_requests = Ejector.get_withdrawal_requests

    def _spy(self, blockstamp):
        requests = get_withdrawal_requests(self, blockstamp)
        reports.append((blockstamp, requests))
        return requests

    monkeypatch.setattr(Ejector, 'get_withdrawal_requests', _spy)
    return reports


def _pubkeys(w3, blockstamp: ReferenceBlockStamp, requests: list[WithdrawalRequest]) -> list[str]:
    validators = w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)
    keys = {
        (gid, validator.lido_id.index): validator.lido_id.key.lower()
        for gid, operator_validators in validators.items()
        for validator in operator_validators
    }
    return [keys[((request.module_id, request.node_operator_id), request.key_index)] for request in requests]


@pytest.mark.fork
@pytest.mark.mainnet
@pytest.mark.integration
@pytest.mark.parametrize('blockstamp_for_forking', [-16], indirect=True)
@pytest.mark.parametrize(
    ('module', 'running_finalized_slots'),
    [(ejector_module, start_before_initial_epoch)],
    indirect=True,
)
def test_ejector_report__sr_phase_2_contracts__withdrawal_requests_queued_in_bus(  # pylint: disable=too-many-positional-arguments
    module,
    report_balance_limit,
    withdrawal_demand,
    set_oracle_members,
    running_finalized_slots,
    reported_requests,
    account_from,
    signer_from,
):
    # Arrange
    w3 = module.w3
    contracts = w3.lido_contracts
    assert contracts.validators_exit_bus_oracle.get_contract_version('latest') == Ejector.COMPATIBLE_CONTRACT_VERSION
    assert contracts.triggerable_withdrawals_bus.get_unprocessed_intents(w3.eth.block_number) == []
    members = set_oracle_members(count=2)

    # Act
    report_frame = None
    switch_finalized, _ = running_finalized_slots
    while switch_finalized():
        for _, private_key in members:
            with account_from(private_key) as account, signer_from(account):
                module.cycle_handler()
        report_frame = module.get_initial_or_current_frame(
            module._receive_last_finalized_slot()  # pylint: disable=protected-access
        )

    # Assert
    assert report_frame is not None
    block = w3.eth.block_number
    assert contracts.validators_exit_bus_oracle.get_last_processing_ref_slot(block) == report_frame.ref_slot
    assert contracts.validators_exit_bus_oracle.get_processing_state(block).data_submitted

    blockstamp, requests = reported_requests[-1]
    assert blockstamp.ref_slot == report_frame.ref_slot
    assert requests, 'The withdrawal queue demand must produce withdrawal requests'
    logger.info(
        f'TESTRUN Reported {len(requests)} requests, {sum(r.is_full for r in requests)} of them full withdrawals'
    )
    intents = contracts.triggerable_withdrawals_bus.get_unprocessed_intents(block)
    assert [(intent.pubkey.lower(), intent.amount) for intent in intents] == list(
        zip(_pubkeys(w3, blockstamp, requests), [request.amount for request in requests], strict=True)
    )
