import logging
from typing import List, Optional

from web3.exceptions import BadFunctionCallOutput, ContractLogicError
from web3.types import BlockIdentifier, Wei

from src.modules.accounting.types import VaultSocket, LatestReportData, VaultInfo
from src.providers.execution.base_interface import ContractInterface

from src.utils.cache import global_lru_cache as lru_cache
from src.utils.types import bytes_to_hex_str

logger = logging.getLogger(__name__)


class LazyOracleContract(ContractInterface):
    abi_path = './assets/LazyOracle.json'

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

    def get_report(self, block_identifier: BlockIdentifier = 'latest') -> Optional[LatestReportData]:
        try:
            response = self.functions.latestReportData.call(block_identifier=block_identifier)

            if response.reportCid == '':
                logger.error(
                    {
                        'msg': 'No data returned from latestReportData().',
                        'block_identifier': repr(block_identifier),
                        'to': self.address,
                    }
                )
                return None

            logger.info(
                {
                    'msg': 'Call `latestReportData()`.',
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

        except (BadFunctionCallOutput, ContractLogicError) as e:
            logger.error(
                {
                    'msg': 'latestReportData() call failed.',
                    'error': str(e),
                    'block_identifier': repr(block_identifier),
                    'to': self.address,
                }
            )
            return None

    def get_vaults(self, block_identifier: BlockIdentifier = 'latest', offset: int = 0, limit: int = 1_000) -> List[VaultInfo]:
        """
            Returns the Vaults
        """
        response = self.functions.batchVaultsInfo(offset, limit).call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': 'Call `batchVaultsInfo(offset, limit).',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )

        out: List[VaultInfo] = []
        for vault in response:
            out.append(VaultInfo(
                vault.vault,
                vault.balance,
                bytes_to_hex_str(vault.withdrawalCredentials),
                vault.liabilityShares,
                vault.shareLimit,
                vault.reserveRatioBP,
                vault.forcedRebalanceThresholdBP,
                vault.infraFeeBP,
                vault.liquidityFeeBP,
                vault.reservationFeeBP,
                vault.pendingDisconnect,
                vault.mintableStETH,
                vault.vaultIndex,
                vault.inOutDelta
            ))

        return out

    def get_all_vaults(self, block_identifier: BlockIdentifier = 'latest', limit: int = 1_000) -> List[VaultInfo]:
        """
        Fetch all vaults using pagination via `get_vaults` in batches of `page_size`.
        """
        vaults: List[VaultInfo] = []
        offset = 0

        total_count = self.get_vaults_count(block_identifier)
        if total_count == 0:
            return []

        while offset < total_count:
            batch = self.get_vaults(block_identifier=block_identifier, offset=offset, limit=limit)
            if not batch:
                break
            vaults.extend(batch)
            offset += limit

        vaults.sort(key=lambda vault: vault.vault_ind)

        return vaults

