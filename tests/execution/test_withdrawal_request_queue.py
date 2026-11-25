from pathlib import Path

import pytest
from eth_tester import EthereumTester, PyEVMBackend
from eth_utils import to_canonical_address
from web3 import EthereumTesterProvider, Web3

from src.providers.execution.withdrawal_request_queue import (
    QUEUE_HEAD_STORAGE_SLOT,
    QUEUE_STORAGE_OFFSET,
    QUEUE_TAIL_STORAGE_SLOT,
    WITHDRAWAL_REQUEST_PREDEPLOY_ADDRESS,
    QueuedWithdrawalRequest,
    get_queued_withdrawal_requests,
)
from src.types import Gwei


# Runtime code of the system contract, cut from the deployment transaction in EIP-7002.
RUNTIME = bytes.fromhex((Path(__file__).parent / 'eip7002_withdrawal_request_runtime.hex').read_text().strip())

PUBKEY_A = bytes(range(1, 49))
PUBKEY_B = bytes(range(0xA0, 0xD0))


def make_w3(storage: dict[int, int] | None = None) -> Web3:
    state = PyEVMBackend.generate_genesis_state(num_accounts=2)
    state[to_canonical_address(WITHDRAWAL_REQUEST_PREDEPLOY_ADDRESS)] = {
        'balance': 0,
        'nonce': 1,
        'code': RUNTIME,
        'storage': storage or {},
    }
    return Web3(EthereumTesterProvider(EthereumTester(PyEVMBackend(genesis_state=state))))


def enqueue(w3: Web3, sender: str, pubkey: bytes, amount: int) -> None:
    fee = int.from_bytes(w3.eth.call({'to': WITHDRAWAL_REQUEST_PREDEPLOY_ADDRESS, 'data': b''}), 'big')
    tx = w3.eth.send_transaction(
        {
            'from': sender,
            'to': WITHDRAWAL_REQUEST_PREDEPLOY_ADDRESS,
            'value': fee,
            'data': pubkey + amount.to_bytes(8, 'big'),
            'gas': 200_000,
        }
    )
    assert w3.eth.get_transaction_receipt(tx)['status'] == 1


@pytest.mark.unit
class TestGetQueuedWithdrawalRequests:
    def test_get_queued_withdrawal_requests__pwr_and_fwr_enqueued__decoded_in_queue_order(self):
        # Arrange
        w3 = make_w3()
        sender_a, sender_b = w3.eth.accounts[:2]
        enqueue(w3, sender_a, PUBKEY_A, 32 * 10**9 + 7)
        enqueue(w3, sender_b, PUBKEY_B, 0)

        # Act
        requests = get_queued_withdrawal_requests(w3, 'latest')

        # Assert
        assert requests == [
            QueuedWithdrawalRequest(sender_a, Web3.to_hex(PUBKEY_A), Gwei(32 * 10**9 + 7)),
            QueuedWithdrawalRequest(sender_b, Web3.to_hex(PUBKEY_B), Gwei(0)),
        ]
        assert [r.is_full for r in requests] == [False, True]

    def test_get_queued_withdrawal_requests__empty_queue__returns_nothing(self):
        assert get_queued_withdrawal_requests(make_w3(), 'latest') == []

    def test_get_queued_withdrawal_requests__dequeued_entries_left_in_storage__ignored(self):
        # Arrange: one request was already dequeued (head = tail = 1) and its slots were never cleared.
        stale = {QUEUE_STORAGE_OFFSET + k: 0xDEAD for k in range(3)}
        w3 = make_w3({QUEUE_HEAD_STORAGE_SLOT: 1, QUEUE_TAIL_STORAGE_SLOT: 1, **stale})
        sender = w3.eth.accounts[0]
        enqueue(w3, sender, PUBKEY_A, 10**9)

        # Act
        requests = get_queued_withdrawal_requests(w3, 'latest')

        # Assert
        assert requests == [QueuedWithdrawalRequest(sender, Web3.to_hex(PUBKEY_A), Gwei(10**9))]
