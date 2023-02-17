from src.web3_extentions.typings import Web3
from src.typings import BlockStamp
from src.services.safe_border import SafeBorder

SLOTS_PER_EPOCH = 2**5
SLOT_TIME = 12

class Finalizer:
    def __init__(self, w3: Web3) -> None:
        self.w3 = w3
        self.safe_border_service = SafeBorder(w3)

    def get_withdrawable_requests(self, is_bunker_mode: bool, share_rate: int, blockstamp: BlockStamp):
        (first_request_id, last_request_id) = self._get_unfinalized_withdrawal_ids(blockstamp)

        if last_request_id - first_request_id == 0:
            return None

        withdrawable_until_epoch = self.safe_border_service.get_safe_border_epoch(is_bunker_mode, blockstamp)
        withdrawable_until_timestamp = withdrawable_until_epoch * SLOTS_PER_EPOCH * SLOT_TIME

        available_eth = self._fetch_locked_ether_amount(blockstamp)

        last_finalizable_request_id_by_timestamp = self._fetch_last_finalizable_request_id_by_timestamp(withdrawable_until_timestamp, first_request_id, last_request_id, blockstamp)
        last_finalizable_request_id_by_budget = self._fetch_last_finalizable_request_id_by_budget(available_eth, share_rate, first_request_id, last_request_id, blockstamp)
        last_request_id = min(last_finalizable_request_id_by_timestamp, last_finalizable_request_id_by_budget)

        if last_request_id - first_request_id <= 0:
            return None
        
        return list(range(first_request_id, last_request_id + 1))

    def _get_unfinalized_withdrawal_ids(self, blockstamp: BlockStamp):
        first_request_id = self._fetch_last_finalized_request_id(blockstamp)
        last_request_id = self._fetch_last_request_id(blockstamp)

        return (first_request_id + 1, last_request_id)

    def _fetch_last_finalizable_request_id_by_budget(self, available_eth: int, share_rate: int, first_request_id: int, last_request_id: int, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue.functions.findLastFinalizableRequestIdByBudget(available_eth, share_rate, first_request_id, last_request_id).call(block_identifier=blockstamp.block_hash)

    def _fetch_last_finalizable_request_id_by_timestamp(self, max_timestamp: int, first_request_id: int, last_request_id: int, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue.functions.getLastFinalizedRequestId(max_timestamp, first_request_id, last_request_id).call(block_identifier=blockstamp.block_hash)

    def _fetch_last_finalized_request_id(self, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue.functions.getLastFinalizedRequestId().call(block_identifier=blockstamp.block_hash)

    def _fetch_last_request_id(self, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue.functions.getLastRequestId().call(block_identifier=blockstamp.block_hash)

    def _fetch_locked_ether_amount(self, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue.functions.getLockedEtherAmount().call(block_identifier=blockstamp.block_hash)