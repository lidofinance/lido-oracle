import logging
from itertools import islice

from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface
from src.variables import EL_REQUESTS_BATCH_SIZE

logger = logging.getLogger(__name__)


class StakingModuleContract(ContractInterface):
    abi_path = './assets/StakingModule.json'

    def get_node_operator_weight(self, operator_ids: list[int], block_identifier: BlockIdentifier) -> list[int]:
        response: list[int] = []

        while node_operators_batch := list(islice(operator_ids, EL_REQUESTS_BATCH_SIZE)):
            weights = self.functions.getOperatorsWeights(node_operators_batch)
            response.extend(weights)

            logger.info({
                'msg': f'Call `getOperatorsWeights({node_operators_batch})`.',
                'response': weights,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            })

        return response
