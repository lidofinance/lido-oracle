import logging
from functools import lru_cache

from web3.types import TxParams, BlockIdentifier

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
        response = self.functions.getProcessingState().call(block_identifier)
        response = named_tuple_to_dataclass(response, AccountingProcessingState)
        logger.info({
            'msg': 'Call `getProcessingState()`.',
            'value': response,
            'block_identifier': block_identifier.__repr__(),
        })
        return response

    def submit_report_extra_data_empty(self) -> TxParams:
        """
        Triggers the processing required when no extra data is present in the report,
        i.e. when extra data format equals EXTRA_DATA_FORMAT_EMPTY.
        """
        tx = self.functions.submitReportExtraDataEmpty()
        logger.info({'msg': 'Build `submitReportExtraDataEmpty()` tx.'})
        return tx

    def submit_report_extra_data_list(self, extra_data: bytes) -> TxParams:
        """
        Submits report extra data in the EXTRA_DATA_FORMAT_LIST format for processing.
        """
        tx = self.functions.submitReportExtraDataList(extra_data)
        logger.info({'msg': 'Build `submitReportExtraDataList({})` tx.'.format(extra_data)})
        return tx
