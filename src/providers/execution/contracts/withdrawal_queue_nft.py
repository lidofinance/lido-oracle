import logging
from src.utils.cache import global_lru_cache as lru_cache

from web3.types import Wei, BlockIdentifier

from src.modules.accounting.types import BatchState, WithdrawalRequestStatus
from src.providers.execution.base_interface import ContractInterface
from src.utils.abi import named_tuple_to_dataclass

logger = logging.getLogger(__name__)


class WithdrawalQueueNftContract(ContractInterface):
    abi_path = './assets/WithdrawalQueueERC721.json'

    @lru_cache(maxsize=1)
    def unfinalized_steth(self, block_identifier: BlockIdentifier = 'latest') -> Wei:
        """
        Returns the amount of stETH in the queue yet to be finalized
        """
        response = self.functions.unfinalizedStETH().call(block_identifier=block_identifier)
        logger.info({
            'msg': 'Call `unfinalizedStETH()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return Wei(response)

    @lru_cache(maxsize=1)
    def bunker_mode_since_timestamp(self, block_identifier: BlockIdentifier = 'latest') -> int:
        """
        Get bunker mode activation timestamp.

        returns `BUNKER_MODE_DISABLED_TIMESTAMP` if bunker mode is disable (i.e., protocol in turbo mode)
        """
        response = self.functions.bunkerModeSinceTimestamp().call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `bunkerModeSinceTimestamp()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def get_last_finalized_request_id(self, block_identifier: BlockIdentifier = 'latest') -> int:
        """
        id of the last finalized request
        NB! requests are indexed from 1, so it returns 0 if there is no finalized requests in the queue
        """
        response = self.functions.getLastFinalizedRequestId().call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `getLastFinalizedRequestId()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def get_withdrawal_status(self, request_id: int, block_identifier: BlockIdentifier = 'latest') -> WithdrawalRequestStatus:
        """
        Returns status for requests with provided ids
        request_id: id of request to check status
        """
        response = self.functions.getWithdrawalStatus([request_id]).call(block_identifier=block_identifier)
        response = named_tuple_to_dataclass(response[0], WithdrawalRequestStatus)

        logger.info({
            'msg': f'Call `getWithdrawalStatus({[request_id]})`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def get_last_request_id(self, block_identifier: BlockIdentifier = 'latest') -> int:
        """
        returns id of the last request
        NB! requests are indexed from 1, so it returns 0 if there is no requests in the queue
        """
        response = self.functions.getLastRequestId().call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `getLastRequestId()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def is_paused(self, block_identifier: BlockIdentifier = 'latest') -> bool:
        """
        Returns whether the withdrawal queue is paused
        """
        response = self.functions.isPaused().call(block_identifier=block_identifier)
        logger.info({
            'msg': 'Call `isPaused()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def max_batches_length(self, block_identifier: BlockIdentifier = 'latest') -> int:
        """
        maximal length of the batch array provided for prefinalization.
        """
        response = self.functions.MAX_BATCHES_LENGTH().call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `MAX_BATCHES_LENGTH()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    def calculate_finalization_batches(
        self,
        share_rate: int,
        timestamp: int,
        max_batch_request_count: int,
        batch_state: tuple,
        block_identifier: BlockIdentifier = 'latest',
    ) -> BatchState:
        """
        Offchain view for the oracle daemon that calculates how many requests can be finalized within
        the given budget, time period and share rate limits. Returned requests are split into batches.
        Each batch consist of the requests that all have the share rate below the `_maxShareRate` or above it.
        """
        response = self.functions.calculateFinalizationBatches(
            share_rate,
            timestamp,
            max_batch_request_count,
            batch_state,
        ).call(block_identifier=block_identifier)
        response = named_tuple_to_dataclass(response, BatchState)

        logger.info({
            'msg': 'Call `calculateFinalizationBatches({}, {}, {}, {})`.'.format(  # pylint: disable=consider-using-f-string
                share_rate,
                timestamp,
                max_batch_request_count,
                batch_state,
            ),
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response
