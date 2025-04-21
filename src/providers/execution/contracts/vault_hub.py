import logging

from web3.types import BlockIdentifier

from src.modules.accounting.types import VaultSocket, LatestReportData
from src.providers.execution.base_interface import ContractInterface

from src.utils.cache import global_lru_cache as lru_cache

logger = logging.getLogger(__name__)


class VaultHubContract(ContractInterface):
    abi_path = './assets/VaultHub.json'

    @lru_cache(maxsize=1)
    def get_vaults_count(self, block_identifier: BlockIdentifier = 'latest') -> int:
        """
        Returns the number of vaults attached to the VaultHub.
        """
        response = self.functions.vaultsCount().call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': 'Call `vaultsCount().',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )

        return response

    @lru_cache(maxsize=1)
    def vault_socket(self, vault_id: int, block_identifier: BlockIdentifier = 'latest') -> VaultSocket:
        """
        Returns the VaultSocket contract for the given vault id.
        """

        response = self.functions.vaultSocket(vault_id).call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': 'Call `vaultSocket(vault_id).',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )

        return VaultSocket(
            response.vault,
            response.shareLimit,
            response.liabilityShares,
            response.reserveRatioBP,
            response.forcedRebalanceThresholdBP,
            response.treasuryFeeBP,
            response.pendingDisconnect,
        )

    def get_report(self, block_identifier: BlockIdentifier = 'latest'):
        response = self.functions.latestReportData.call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': 'Call `latestReportData().',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )

        return LatestReportData(
            response.timestamp,
            response.treeRoot,
            response.reportCid,
        )
