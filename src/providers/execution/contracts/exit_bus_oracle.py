import logging
from functools import lru_cache
from typing import Sequence

from web3.types import BlockIdentifier

from src.modules.ejector.typings import EjectorProcessingState
from src.providers.execution.contracts.base_oracle import BaseOracleContract
from src.utils.abi import named_tuple_to_dataclass


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
            'block_identifier': block_identifier.__repr__(),
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
            'block_identifier': block_identifier.__repr__(),
        })
        return response

    @lru_cache(maxsize=1)
    def get_last_requested_validator_indices(
        self,
        module_id: int,
        node_operators_ids_in_module: Sequence[int],
        block_identifier: BlockIdentifier = 'latest',
    ) -> list[int]:
        """
        Returns the latest validator indices that were requested to exit for the given
        `nodeOpIds` in the given `moduleId`. For node operators that were never requested to exit
        any validator, index is set to -1.
        """
        response = self.functions.getLastRequestedValidatorIndices(
            module_id,
            node_operators_ids_in_module,
        ).call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `getLastRequestedValidatorIndices({}, {})`.'.format(module_id, node_operators_ids_in_module),
            'value': response,
            'block_identifier': block_identifier.__repr__(),
        })
        return response