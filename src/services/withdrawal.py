from src.web3py.typings import Web3
from src.typings import BlockStamp
from src.services.safe_border import SafeBorder
from src.modules.submodules.consensus import ChainConfig

class Withdrawal:
    def __init__(self, w3: Web3) -> None:
        self.w3 = w3
        self.safe_border_service = SafeBorder(w3)

    def get_next_last_finalizable_id(
        self, 
        is_bunker_mode: bool, 
        share_rate: int, 
        withdrawal_vault_balance: int, 
        el_rewards_vault_balance: int, 
        blockstamp: BlockStamp, 
        chain_config: ChainConfig
    ) -> int:
        if not self._has_unfinalized_requests(blockstamp):
            return 0

        self.chain_config = chain_config

        withdrawable_until_epoch = self.safe_border_service.get_safe_border_epoch(is_bunker_mode, blockstamp)
        withdrawable_until_timestamp = chain_config.genesis_time + (withdrawable_until_epoch * chain_config.slots_per_epoch * chain_config.seconds_per_slot)
        available_eth = self._get_available_eth(withdrawal_vault_balance, el_rewards_vault_balance, blockstamp)
        
        return self._fetch_last_finalizable_request_id(available_eth, share_rate, withdrawable_until_timestamp, blockstamp)

    def _has_unfinalized_requests(self, blockstamp: BlockStamp) -> bool:
        first_request_id = self._fetch_last_finalized_request_id(blockstamp)
        last_request_id = self._fetch_last_request_id(blockstamp)

        return first_request_id != last_request_id

    def _get_available_eth(self, withdrawal_vault_balance: int, el_rewards_vault_balance: int, blockstamp: BlockStamp) -> int:
        buffered_ether = self._fetch_buffered_ether(blockstamp)
        unfinalized_steth = self._fetch_unfinalized_steth(blockstamp)

        reserved_buffer = min(buffered_ether, unfinalized_steth)

        return withdrawal_vault_balance + el_rewards_vault_balance + reserved_buffer

    def _fetch_last_finalizable_request_id(self, available_eth: int, share_rate: int, withdrawable_until_timestamp: int, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.findLastFinalizableRequestId(available_eth, share_rate, withdrawable_until_timestamp).call(block_identifier=blockstamp.block_hash)

    def _fetch_last_finalized_request_id(self, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.getLastFinalizedRequestId().call(block_identifier=blockstamp.block_hash)

    def _fetch_last_request_id(self, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.getLastRequestId().call(block_identifier=blockstamp.block_hash)

    def _fetch_buffered_ether(self, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.lido.functions.getBufferedEther().call(block_identifier=blockstamp.block_hash)

    def _fetch_unfinalized_steth(self, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.unfinalizedStETH().call(block_identifier=blockstamp.block_hash)