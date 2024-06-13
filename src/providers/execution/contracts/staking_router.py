import logging
from src.utils.cache import global_lru_cache as lru_cache

from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface
from src.utils.dataclass import list_of_dataclasses
from src.web3py.extensions.lido_validators import StakingModule, NodeOperator

logger = logging.getLogger(__name__)


class StakingRouterContract(ContractInterface):
    abi_path = './assets/StakingRouter.json'

    @lru_cache(maxsize=1)
    def get_contract_version(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self.functions.getContractVersion().call(block_identifier=block_identifier)
        logger.info(
            {
                'msg': 'Call `getContractVersion()`.',
                'value': response,
                'block_identifier': repr(block_identifier),
            }
        )
        return response

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
        })
        return response

    def get_all_node_operator_digests(self, module: StakingModule, block_identifier: BlockIdentifier = 'latest') -> list[NodeOperator]:
        """
        Returns node operator digest for each node operator in lido protocol
        """
        response = self.functions.getAllNodeOperatorDigests(module.id).call(block_identifier=block_identifier)
        response = [NodeOperator.from_response(no, module) for no in response]

        logger.info({
            'msg': f'Call `getAllNodeOperatorDigests({module.id})`.',
            # Too long response
            'value': len(response),
            'block_identifier': repr(block_identifier),
        })
        return response


class StakingRouterContractV2(StakingRouterContract):
    abi_path = './assets/StakingRouterV2.json'

    @lru_cache(maxsize=1)
    @list_of_dataclasses(StakingModule.from_response)
    def get_staking_modules(self, block_identifier: BlockIdentifier = 'latest') -> list[StakingModule]:
        """
        Returns all registered staking modules
        """
        contract_version = self.get_contract_version(block_identifier)

        if contract_version == 1:
            # Backward compatibility in case if new oracle have to build report for old protocol version
            # But latest contracts has new version
            logger.warning({'msg': 'Use StakingRouter.json abi (old one) to parse the response.'})
            staking_router = self.w3.eth.contract(
                address=self.address,
                abi=self.load_abi(super().abi_path),
                decode_tuples=True,
            )
            response = staking_router.functions.getStakingModules().call(block_identifier=block_identifier)
        else:
            response = self.functions.getStakingModules().call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `getStakingModules()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
        })
        return response
