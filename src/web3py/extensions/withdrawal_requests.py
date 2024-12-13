import logging

from web3 import Web3
from web3.module import Module

from src.providers.execution.exceptions import InconsistentData
from src.types import BlockStamp

logger = logging.getLogger(__name__)


class WithdrawalRequests(Module):
    """
    Web3py extension to work with EIP-7002 withdrawal requests.
    See https://eips.ethereum.org/EIPS/eip-7002 for details.
    """

    w3: Web3

    ADDRESS = Web3.to_checksum_address("0x0c15F14308530b7CDB8460094BbB9cC28b9AaaAA")

    QUEUE_HEAD_SLOT = 2
    QUEUE_TAIL_SLOT = 3

    def get_queue_len(self, blockstamp: BlockStamp):
        head = self.w3.eth.get_storage_at(self.ADDRESS, self.QUEUE_HEAD_SLOT, block_identifier=blockstamp.block_hash)
        tail = self.w3.eth.get_storage_at(self.ADDRESS, self.QUEUE_TAIL_SLOT, block_identifier=blockstamp.block_hash)
        if head > tail:
            raise InconsistentData("EIP-7002 queue's head is over the tail")
        return int.from_bytes(tail) - int.from_bytes(head)
