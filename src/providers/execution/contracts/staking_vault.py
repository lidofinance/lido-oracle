import logging

from src.providers.execution.base_interface import ContractInterface

from web3.types import BlockIdentifier

from src.utils.cache import global_lru_cache as lru_cache
from src.utils.types import bytes_to_hex_str

logger = logging.getLogger(__name__)


class StakingVaultContract(ContractInterface):
    abi_path = './assets/StakingVault.json'

    @lru_cache(maxsize=1)
    def withdrawal_credentials(self, block_identifier: BlockIdentifier = 'latest') -> str:
        """
        Returns the withdrawal credentials of the vault.
        """
        response = self.functions.withdrawalCredentials().call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': 'Call `withdrawalCredentials().',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )

        return bytes_to_hex_str(response)

    @lru_cache(maxsize=1)
    def in_out_delta(self, block_identifier: BlockIdentifier = 'latest') -> int:
        """
        Returns the delta of the in and out values of the vault.
        """
        response = self.functions.inOutDelta().call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': 'Call `inOutDelta().',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )

        return response
