import logging

from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface
from src.types import NodeOperatorId
from src.utils.cache import global_lru_cache as lru_cache


logger = logging.getLogger(__name__)


class CustomFeeRegistryContract(ContractInterface):
    abi_path = './assets/CustomFeeRegistry.json'

    @lru_cache()
    def get_fee_share_discount(self, no_id: NodeOperatorId, block_identifier: BlockIdentifier) -> int:
        """
        Returns the current fee share discount of the node operator in basis points. Pending cuts are not included
        """
        response = self.functions.getFeeShareDiscount(no_id).call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': f'Call `getFeeShareDiscount({no_id})`.',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )
        return response

    @lru_cache()
    def fee_share_discount_step(self, block_identifier: BlockIdentifier) -> int:
        """
        Returns the step the fee share discount must be a multiple of, in basis points
        """
        response = self.functions.FEE_SHARE_DISCOUNT_STEP().call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': 'Call `FEE_SHARE_DISCOUNT_STEP()`.',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )
        return response
