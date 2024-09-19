import logging
from src.utils.cache import global_lru_cache as lru_cache

from web3.types import BlockIdentifier

from src.modules.accounting.types import SharesRequestedToBurn
from src.providers.execution.base_interface import ContractInterface
from src.utils.abi import named_tuple_to_dataclass


logger = logging.getLogger(__name__)


class BurnerContract(ContractInterface):
    abi_path = './assets/Burner.json'

    @lru_cache(maxsize=1)
    def get_shares_requested_to_burn(self, block_identifier: BlockIdentifier = 'latest') -> SharesRequestedToBurn:
        """
        Returns the current amount of shares locked on the contract to be burnt.
        """
        response = self.functions.getSharesRequestedToBurn().call(block_identifier=block_identifier)

        response = named_tuple_to_dataclass(response, SharesRequestedToBurn)
        logger.info({
            'msg': 'Call `getSharesRequestedToBurn()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response
