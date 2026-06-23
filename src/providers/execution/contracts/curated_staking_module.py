import logging
from itertools import islice

from eth_typing import ChecksumAddress
from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface
from src.types import NodeOperatorId
from src.variables import EL_REQUESTS_BATCH_SIZE


logger = logging.getLogger(__name__)


class CuratedStakingModuleContract(ContractInterface):
    abi_path = './assets/CuratedStakingModule.json'

    def get_operator_weights(
        self,
        operator_ids: list[NodeOperatorId],
        block_identifier: BlockIdentifier,
    ) -> list[int]:
        response: list[int] = []
        operator_ids_iter = iter(operator_ids)

        while node_operators_batch := list(islice(operator_ids_iter, EL_REQUESTS_BATCH_SIZE)):
            weights = self.functions.getOperatorWeights(node_operators_batch).call(block_identifier=block_identifier)
            response.extend(weights)

            logger.info(
                {
                    'msg': f'Call `getOperatorWeights({node_operators_batch})`.',
                    'response': weights,
                    'block_identifier': repr(block_identifier),
                    'to': self.address,
                }
            )

        return response

    def get_type(self, block_identifier: BlockIdentifier) -> bytes:
        response = self.functions.getType().call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': 'Call `getType()`.',
                'response': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )

        return response

    def get_meta_registry_address(self, block_identifier: BlockIdentifier) -> ChecksumAddress:
        response = self.functions.META_REGISTRY().call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': 'Call `getMetaRegistry()`.',
                'response': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )

        return response

    def get_node_operator_deposit_info_to_update_count(self, block_identifier: BlockIdentifier) -> int:
        response = self.functions.getNodeOperatorDepositInfoToUpdateCount().call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': 'Call `getNodeOperatorDepositInfoToUpdateCount()`.',
                'response': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )

        return response
