import logging
from itertools import batched

from src.providers.execution.contracts.pausable import PausableContract
from src.utils.cache import global_lru_cache as lru_cache
from typing import Sequence

from web3.types import BlockIdentifier

from src.modules.ejector.types import EjectorProcessingState
from src.providers.execution.contracts.base_oracle import BaseOracleContract
from src.utils.abi import named_tuple_to_dataclass
from src.variables import EL_REQUESTS_BATCH_SIZE

logger = logging.getLogger(__name__)


class ExitBusOracleContract(BaseOracleContract, PausableContract):
    abi_path = './assets/ValidatorsExitBusOracle.json'

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
        result = []

        for no_list in batched(node_operators_ids_in_module, EL_REQUESTS_BATCH_SIZE):
            response = self.functions.getLastRequestedValidatorIndices(
                module_id,
                no_list,
            ).call(block_identifier=block_identifier)

            logger.info({
                'msg': f'Call `getLastRequestedValidatorIndices({module_id}, {len(no_list)})`.',
                'len': len(response),
                'block_identifier': repr(block_identifier),
                'to': self.address,
            })

            result.extend(response)

        return result
