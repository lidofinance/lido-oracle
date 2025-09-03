import logging

from src.modules.accounting.types import StakingFeeAggregateDistribution
from src.utils.abi import named_tuple_to_dataclass
from src.utils.cache import global_lru_cache as lru_cache

from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface
from src.utils.dataclass import list_of_dataclasses
from src.web3py.extensions.lido_validators import StakingModule, NodeOperator
from src.variables import EL_REQUESTS_BATCH_SIZE

logger = logging.getLogger(__name__)


class StakingRouterContract(ContractInterface):
    abi_path = './assets/StakingRouter.json'

    @lru_cache(maxsize=1)
    def get_contract_version(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self.functions.getContractVersion().call(block_identifier=block_identifier)
        logger.debug(
            {
                'msg': 'Call `getContractVersion()`.',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )
        return response

    def get_all_node_operator_digests(self, module: StakingModule, block_identifier: BlockIdentifier = 'latest') -> list[NodeOperator]:
        """
        Returns node operator digests for each node operator in staking module
        """
        response: list = []
        i = 0

        while True:
            nos = self.functions.getNodeOperatorDigests(
                module.id,
                i * EL_REQUESTS_BATCH_SIZE,
                EL_REQUESTS_BATCH_SIZE,
            ).call(block_identifier=block_identifier)

            logger.info({
                'msg': f'Call `getNodeOperatorDigests({module.id}, {i * EL_REQUESTS_BATCH_SIZE}, {EL_REQUESTS_BATCH_SIZE})`.',
                # Too long response
                'len': len(nos),
                'block_identifier': repr(block_identifier),
                'to': self.address,
            })

            i += 1
            response.extend(nos)

            if len(nos) != EL_REQUESTS_BATCH_SIZE:
                break

        return [NodeOperator.from_response(no, module) for no in response]

    @lru_cache(maxsize=1)
    @list_of_dataclasses(StakingModule.from_response)
    def get_staking_modules(self, block_identifier: BlockIdentifier = 'latest') -> list[StakingModule]:
        """
        Returns all registered staking modules
        """
        response = self.functions.getStakingModules().call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `getStakingModules()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    def get_staking_fee_aggregate_distribution(self, block_identifier: BlockIdentifier = 'latest') -> StakingFeeAggregateDistribution:
        """
        Returns all registered staking modules
        """
        response = self.functions.getStakingFeeAggregateDistribution().call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `getStakingFeeAggregateDistribution()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        response = named_tuple_to_dataclass(response, StakingFeeAggregateDistribution)
        return response
