import logging
from dataclasses import dataclass

from eth_typing import ChecksumAddress, HexStr
from web3 import Web3
from web3.types import BlockIdentifier

from src.types import Gwei


logger = logging.getLogger(__name__)

# https://eips.ethereum.org/EIPS/eip-7002#configuration
WITHDRAWAL_REQUEST_PREDEPLOY_ADDRESS = Web3.to_checksum_address('0x00000961Ef480Eb55e80D19ad83579A64c007002')
QUEUE_HEAD_STORAGE_SLOT = 2
QUEUE_TAIL_STORAGE_SLOT = 3
QUEUE_STORAGE_OFFSET = 4
SLOTS_PER_REQUEST = 3


@dataclass(frozen=True)
class QueuedWithdrawalRequest:
    """A request in the EIP-7002 queue, not yet dequeued to the CL. `amount == 0` is a full withdrawal."""

    source_address: ChecksumAddress
    pubkey: HexStr
    amount: Gwei

    @property
    def is_full(self) -> bool:
        return self.amount == 0


def decode_queued_request(
    address_word: bytes, pubkey_word: bytes, pubkey_amount_word: bytes
) -> QueuedWithdrawalRequest:
    """
    The system contract stores each request in three words:
    - 12 zero bytes ++ source address;
    - pubkey[0:32];
    - pubkey[32:48] ++ amount ++ 8 zero bytes. The amount keeps the big-endian calldata order;
      only the dequeued output is little-endian.
    """
    return QueuedWithdrawalRequest(
        source_address=Web3.to_checksum_address(address_word[12:32]),
        pubkey=Web3.to_hex(pubkey_word + pubkey_amount_word[:16]),
        amount=Gwei(int.from_bytes(pubkey_amount_word[16:24], 'big')),
    )


def get_queued_withdrawal_requests(w3: Web3, block_identifier: BlockIdentifier) -> list[QueuedWithdrawalRequest]:
    """
    Requests between the queue head and tail, in dequeue order. Slots outside that range can hold
    already dequeued requests: the contract resets the pointers without clearing them.
    """

    def read(slot: int) -> bytes:
        return bytes(w3.eth.get_storage_at(WITHDRAWAL_REQUEST_PREDEPLOY_ADDRESS, slot, block_identifier))

    head = int.from_bytes(read(QUEUE_HEAD_STORAGE_SLOT), 'big')
    tail = int.from_bytes(read(QUEUE_TAIL_STORAGE_SLOT), 'big')

    requests = []
    for index in range(head, tail):
        base = QUEUE_STORAGE_OFFSET + index * SLOTS_PER_REQUEST
        requests.append(decode_queued_request(read(base), read(base + 1), read(base + 2)))

    logger.info(
        {
            'msg': 'Read the EIP-7002 withdrawal request queue.',
            'count': len(requests),
            'block_identifier': repr(block_identifier),
        }
    )
    return requests
