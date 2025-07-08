import logging
from web3.types import BlockIdentifier
from src import variables
from src.modules.accounting.types import LatestReportData, VaultInfo
from src.providers.execution.base_interface import ContractInterface
from src.utils.abi import named_tuple_to_dataclass
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.dataclass import list_of_dataclasses

logger = logging.getLogger(__name__)


class VaultsLazyOracleContract(ContractInterface):
    abi_path = './assets/LazyOracle.json'

    @lru_cache(maxsize=1)
    def get_vaults_count(self, block_identifier: BlockIdentifier = 'latest') -> int:
        """
        Returns the number of vaults attached to the VaultHub.
        """
        response = self.functions.vaultsCount.call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': 'Call `vaultsCount().',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )

        return response

    def get_latest_report(self, block_identifier: BlockIdentifier = 'latest') -> LatestReportData:
        response = self.functions.latestReportData.call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': 'Call `latestReportData()`.',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )

        response = named_tuple_to_dataclass(response, LatestReportData)
        return response

    @list_of_dataclasses(VaultInfo.from_response)
    def get_vaults(self, offset: int, limit: int, block_identifier: BlockIdentifier = 'latest') -> list[VaultInfo]:
        """
        Returns the Vaults
        """
        response = self.functions.batchVaultsInfo(offset, limit).call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': f'Call `batchVaultsInfo({offset}, {limit}).',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )

        return response

    def get_all_vaults(self, block_identifier: BlockIdentifier = 'latest') -> list[VaultInfo]:
        """
        Fetch all vaults using pagination via `get_vaults` in batches of `page_size`.
        """
        vaults: list[VaultInfo] = []
        offset = 0

        total_count = self.get_vaults_count(block_identifier)
        if total_count == 0:
            return []

        while offset < total_count:
            batch = self.get_vaults(block_identifier=block_identifier, offset=offset, limit=variables.VAULT_PAGINATION_LIMIT)
            if not batch:
                break
            vaults.extend(batch)
            offset += variables.VAULT_PAGINATION_LIMIT

        return vaults
