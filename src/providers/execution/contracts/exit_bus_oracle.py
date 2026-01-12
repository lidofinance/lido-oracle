import logging

from web3.types import BlockIdentifier

from src.modules.ejector.types import EjectorProcessingState
from src.providers.execution.contracts.base_oracle import BaseOracleContract
from src.utils.abi import named_tuple_to_dataclass
from src.utils.cache import global_lru_cache as lru_cache

logger = logging.getLogger(__name__)


class ExitBusOracleContract(BaseOracleContract):
    abi_path = './assets/ValidatorsExitBusOracle.json'

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

    @lru_cache(maxsize=1)
    def get_processing_state(self, block_identifier: BlockIdentifier = 'latest') -> EjectorProcessingState:
        """
        Returns data processing state for the current reporting frame.
        """
        response = self.functions.getProcessingState().call(block_identifier=block_identifier)
        response = named_tuple_to_dataclass(response, EjectorProcessingState)
        logger.info({
            'msg': 'Call `getProcessingState()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response
