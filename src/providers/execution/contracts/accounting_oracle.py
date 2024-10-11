import logging
from src.utils.cache import global_lru_cache as lru_cache

from web3.contract.contract import ContractFunction
from web3.types import BlockIdentifier

from src.modules.accounting.types import AccountingProcessingState
from src.providers.execution.contracts.base_oracle import BaseOracleContract
from src.utils.abi import named_tuple_to_dataclass


logger = logging.getLogger(__name__)


class AccountingOracleContract(BaseOracleContract):
    abi_path = './assets/AccountingOracle.json'

    @lru_cache(maxsize=1)
    def get_processing_state(self, block_identifier: BlockIdentifier = 'latest') -> AccountingProcessingState:
        """
        Returns data processing state for the current reporting frame.
        """
        response = self.functions.getProcessingState().call(block_identifier=block_identifier)
        response = named_tuple_to_dataclass(response, AccountingProcessingState)
        logger.info({
            'msg': 'Call `getProcessingState()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    def submit_report_extra_data_empty(self) -> ContractFunction:
        """
        Triggers the processing required when no extra data is present in the report,
        i.e. when extra data format equals EXTRA_DATA_FORMAT_EMPTY.
        """
        tx = self.functions.submitReportExtraDataEmpty()
        logger.info({'msg': 'Build `submitReportExtraDataEmpty()` tx.'})
        return tx

    def submit_report_extra_data_list(self, extra_data: bytes) -> ContractFunction:
        """
        Submits report extra data in the EXTRA_DATA_FORMAT_LIST format for processing.
        """
        tx = self.functions.submitReportExtraDataList(extra_data)
        logger.info({'msg': f'Build `submitReportExtraDataList({extra_data.hex()})` tx.'})
        return tx
