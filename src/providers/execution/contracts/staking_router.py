import logging
from functools import lru_cache

from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface
from src.utils.dataclass import list_of_dataclasses
from src.web3py.extensions.lido_validators import StakingModule, NodeOperator

logger = logging.getLogger(__name__)


class StakingRouterContract(ContractInterface):
    abi_path = './assets/StakingRouter.json'

    @lru_cache(maxsize=1)
    @list_of_dataclasses(StakingModule)
    def get_staking_modules(self, block_identifier: BlockIdentifier = 'latest') -> list[StakingModule]:
        """
        Returns all registered staking modules
        """
        response = self.functions.getStakingModules().call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `getStakingModules()`.',
            'value': response,
            'block_identifier': block_identifier.__repr__(),
        })
        return response

    @lru_cache(maxsize=1)
    def get_all_node_operator_digests(self, module: StakingModule, block_identifier: BlockIdentifier = 'latest') -> list[NodeOperator]:
        """
        Returns node operator digest for each node operator in lido protocol
        """
        response = self.functions.getAllNodeOperatorDigests(module.id).call(block_identifier=block_identifier)
        response = [NodeOperator.from_response(no, module) for no in response]

        logger.info({
            'msg': 'Call `getAllNodeOperatorDigests({})`.'.format(module.id),
            'value': response,
            'block_identifier': block_identifier.__repr__(),
        })
        return response
