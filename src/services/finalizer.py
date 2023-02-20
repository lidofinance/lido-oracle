from src.web3py.typings import Web3
from src.typings import BlockStamp
from src.services.safe_border import SafeBorder

SLOTS_PER_EPOCH = 2**5
SLOT_TIME = 12

class Finalizer:
    def __init__(self, w3: Web3) -> None:
        self.w3 = w3
        self.safe_border_service = SafeBorder(w3)

    def get_next_last_finalizable_id(self, is_bunker_mode: bool, share_rate: int, blockstamp: BlockStamp) -> int:
        if not self._has_unfinalized_requests(blockstamp):
            return 0

        withdrawable_until_epoch = self.safe_border_service.get_safe_border_epoch(is_bunker_mode, blockstamp)
        withdrawable_until_timestamp = withdrawable_until_epoch * SLOTS_PER_EPOCH * SLOT_TIME
        available_eth = self._fetch_locked_ether_amount(blockstamp)
        
        return self._fetch_last_finalizable_request_id(available_eth, share_rate, withdrawable_until_timestamp, blockstamp)

    def _has_unfinalized_requests(self, blockstamp: BlockStamp) -> bool:
        first_request_id = self._fetch_last_finalized_request_id(blockstamp)
        last_request_id = self._fetch_last_request_id(blockstamp)

        return first_request_id != last_request_id

    def _fetch_last_finalizable_request_id(self, available_eth: int, share_rate: int, withdrawable_until_timestamp: int, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.findLastFinalizableRequestId(available_eth, share_rate, withdrawable_until_timestamp).call(block_identifier=blockstamp.block_hash)

    def _fetch_last_finalized_request_id(self, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.getLastFinalizedRequestId().call(block_identifier=blockstamp.block_hash)

    def _fetch_last_request_id(self, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.getLastRequestId().call(block_identifier=blockstamp.block_hash)

    def _fetch_locked_ether_amount(self, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.getLockedEtherAmount().call(block_identifier=blockstamp.block_hash)