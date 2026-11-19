import logging
from dataclasses import dataclass

from eth_typing import HexStr
from web3 import Web3
from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface
from src.types import Gwei
from src.utils.cache import global_lru_cache as lru_cache
from src.variables import EL_REQUESTS_BATCH_SIZE


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WithdrawalIntent:
    """A queued request that the Bus has not sent to EIP-7002 yet. `amount == 0` is a full withdrawal."""

    pubkey: HexStr
    amount: Gwei

    @property
    def is_full(self) -> bool:
        return self.amount == 0


class TriggerableWithdrawalsBusContract(ContractInterface):
    abi_path = './assets/TriggerableWithdrawalsBus.json'

    @lru_cache(maxsize=1)
    def get_unprocessed_intents(self, block_identifier: BlockIdentifier) -> list[WithdrawalIntent]:
        """All queued intents in execution order."""
        count = self.functions.unprocessedIntentsCount().call(block_identifier=block_identifier)

        intents: list[WithdrawalIntent] = []
        for offset in range(0, count, EL_REQUESTS_BATCH_SIZE):
            page = self.functions.getWithdrawalIntents(offset, EL_REQUESTS_BATCH_SIZE).call(
                block_identifier=block_identifier
            )
            intents.extend(WithdrawalIntent(pubkey=Web3.to_hex(i.pubkey), amount=Gwei(i.amount)) for i in page)

        logger.info(
            {
                'msg': 'Call `getWithdrawalIntents()`.',
                'count': count,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )
        return intents
