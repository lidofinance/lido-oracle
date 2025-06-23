import logging

from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface


logger = logging.getLogger(__name__)


class NodeOperatorRegistry(ContractInterface):
    abi_path = './assets/NodeOperatorRegistry.json'

    def get_type(self, block_identifier: BlockIdentifier = 'latest') -> bytes:
        response = self.functions.getType().call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `getType()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    def distribute_reward(self):
        tx = self.functions.distributeReward()
        logger.info({'msg': 'Build `distributeReward()` tx.'})
        return tx
