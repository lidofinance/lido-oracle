import logging

from eth_typing import BlockIdentifier

from src.utils.cache import global_lru_cache as lru_cache
from src.providers.execution.base_interface import ContractInterface


logger = logging.getLogger(__name__)


class PausableContract(ContractInterface):
    @lru_cache(maxsize=1)
    def is_paused(self, block_identifier: BlockIdentifier = 'latest') -> bool:
        """
        Returns whether the contract is paused.
        """
        response = self.functions.isPaused().call(block_identifier=block_identifier)
        logger.info({
            'msg': 'Call `isPaused()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response
