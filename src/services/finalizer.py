from src.web3_extentions.typings import Web3
from src.typings import BlockStamp
from src.services.safe_border import SafeBorder

SLOTS_PER_EPOCH = 2**5
SLOT_TIME = 12

class Finalizer:
    def __init__(self, w3: Web3) -> None:
        self.w3 = w3
        self.safe_border_service = SafeBorder(w3)

    def get_withdrawable_requests(self, is_bunker: bool, share_rate: int, blockstamp: BlockStamp) -> None | list(int):
        (start_id, end_id) = self.get_unfinalized_withdrawal_ids(blockstamp)

        if end_id - start_id == 0:
            return None

        withdrawable_until_epoch = self.safe_border_service(is_bunker, blockstamp)
        withdrawable_until_timestamp = withdrawable_until_epoch * SLOTS_PER_EPOCH * SLOT_TIME

        available_eth = self.fetch_locked_ether_amount(blockstamp)

        last_finalizable_request_id_by_timestamp = self.fetch_last_finalizable_request_id(withdrawable_until_timestamp, start_id, end_id, blockstamp)
        last_finalizable_request_id_by_budget = self.fetch_last_finalizable_request_id(available_eth, share_rate, start_id, end_id, blockstamp)
        end_id = min(last_finalizable_request_id_by_timestamp, last_finalizable_request_id_by_budget)

        if end_id - start_id == 0:
            return None
        
        return list(range(start_id, end_id + 1))

    def get_unfinalized_withdrawal_ids(self, blockstamp: BlockStamp):
        start_id = self.fetch_last_finalized_request_id(blockstamp)
        end_id = self.fetch_last_request_id(blockstamp)

        return (start_id, end_id)

    def fetch_last_finalizable_request_id_by_budget(self, available_eth: int, share_rate: int, start_id: int, end_id: int, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue.functions.findLastFinalizableRequestIdByBudget(available_eth, share_rate, start_id, end_id).call(block_identifier=blockstamp.block_hash)

    def fetch_last_finalizable_request_id_by_timestamp(self, max_timestamp: int, start_id: int, end_id: int, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue.functions.getLastFinalizedRequestId(max_timestamp, start_id, end_id).call(block_identifier=blockstamp.block_hash)

    def fetch_last_finalized_request_id(self, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue.functions.getLastFinalizedRequestId().call(block_identifier=blockstamp.block_hash)

    def fetch_last_request_id(self, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue.functions.getLastRequestId().call(block_identifier=blockstamp.block_hash)

    def fetch_locked_ether_amount(self, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue.functions.getLockedEtherAmount().call(block_identifier=blockstamp.block_hash)