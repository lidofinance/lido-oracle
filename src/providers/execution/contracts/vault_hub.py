import logging

from src.modules.accounting.types import VaultSocket
from src.providers.execution.base_interface import ContractInterface

from src.types import BlockStamp
from src.utils.cache import global_lru_cache as lru_cache

logger = logging.getLogger(__name__)


class VaultHubContract(ContractInterface):
    abi_path = './assets/VaultHub.json'

    @lru_cache(maxsize=1)
    def get_vaults_count(self, blockstamp: BlockStamp) -> int:
        """
        Returns the number of vaults attached to the VaultHub.
        """
        response = self.functions.vaultsCount().call(block_identifier=blockstamp.block_hash)

        logger.info({
            'msg': 'Call `vaultsCount().',
            'value': response,
            'block_identifier': repr(blockstamp.block_hash),
            'to': self.address,
        })

        return response

    @lru_cache(maxsize=1)
    def vault_socket(self, vault_id: int, blockstamp: BlockStamp) -> VaultSocket:
        """
        Returns the VaultSocket contract for the given vault id.
        """

        response = self.functions.vaultSocket(vault_id).call(block_identifier=blockstamp.block_hash)

        logger.info({
            'msg': 'Call `vaultSocket(vault_id).',
            'value': response,
            'block_identifier': repr(blockstamp.block_hash),
            'to': self.address,
        })

        return response
