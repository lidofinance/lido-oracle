import logging
from src.utils.cache import global_lru_cache as lru_cache

from web3.types import BlockIdentifier

from src.modules.accounting.types import OracleReportLimits
from src.providers.execution.base_interface import ContractInterface
from src.utils.abi import named_tuple_to_dataclass


logger = logging.getLogger(__name__)


class OracleReportSanityCheckerContract(ContractInterface):
    abi_path = './assets/OracleReportSanityChecker.json'

    @lru_cache(maxsize=1)
    def get_oracle_report_limits(self, block_identifier: BlockIdentifier = 'latest') -> OracleReportLimits:
        """
        Returns the limits list for the Lido's oracle report sanity checks
        """
        response = self.functions.getOracleReportLimits().call(block_identifier=block_identifier)
        response = named_tuple_to_dataclass(response, OracleReportLimits.from_response)

        logger.info({
            'msg': 'Call `getOracleReportLimits()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response
