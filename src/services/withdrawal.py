from web3.types import Wei

from src.web3py.typings import Web3
from src.typings import BlockStamp
from src.services.safe_border import SafeBorder
from src.modules.submodules.consensus import ChainConfig, FrameConfig


class Withdrawal:
    chain_config: ChainConfig
    frame_config: FrameConfig
    blockstamp: BlockStamp

    def __init__(
        self, 
        w3: Web3, 
        blockstamp: BlockStamp, 
        chain_config: ChainConfig,
        frame_config: FrameConfig
    ) -> None:
        self.w3 = w3
        self.safe_border_service = SafeBorder(self.w3, blockstamp, chain_config, frame_config)
        
        self.chain_config = chain_config
        self.frame_config = frame_config
        self.blockstamp = blockstamp

    def get_next_last_finalizable_id(
        self,
        is_bunker_mode: bool,
        share_rate: int,
        withdrawal_vault_balance: int,
        el_rewards_vault_balance: int
    ) -> int:
        if not self._has_unfinalized_requests():
            return 0

        withdrawable_until_epoch = self.safe_border_service.get_safe_border_epoch(is_bunker_mode)
        withdrawable_until_timestamp = self.chain_config.genesis_time + (withdrawable_until_epoch * self.chain_config.slots_per_epoch * self.chain_config.seconds_per_slot)
        available_eth = self._get_available_eth(withdrawal_vault_balance, el_rewards_vault_balance)
        
        return self._fetch_last_finalizable_request_id(available_eth, share_rate, withdrawable_until_timestamp)

    def _has_unfinalized_requests(self) -> bool:
        first_request_id = self._fetch_last_finalized_request_id()
        last_request_id = self._fetch_last_request_id()

        return first_request_id != last_request_id

    def _get_available_eth(self, withdrawal_vault_balance: Wei, el_rewards_vault_balance: Wei) -> Wei:
        buffered_ether = self._fetch_buffered_ether()
        unfinalized_steth = self._fetch_unfinalized_steth()

        reserved_buffer = min(buffered_ether, unfinalized_steth)

        return withdrawal_vault_balance + el_rewards_vault_balance + reserved_buffer

    def _fetch_last_finalizable_request_id(self, available_eth: int, share_rate: int, withdrawable_until_timestamp: int) -> int:
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.findLastFinalizableRequestId(available_eth, share_rate, withdrawable_until_timestamp).call(block_identifier=self.blockstamp.block_hash)

    def _fetch_last_finalized_request_id(self) -> int:
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.getLastFinalizedRequestId().call(block_identifier=self.blockstamp.block_hash)

    def _fetch_last_request_id(self) -> int:
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.getLastRequestId().call(block_identifier=self.blockstamp.block_hash)

    def _fetch_buffered_ether(self) -> Wei:
        return Wei(self.w3.lido_contracts.lido.functions.getBufferedEther().call(block_identifier=self.blockstamp.block_hash))

    def _fetch_unfinalized_steth(self) -> Wei:
        return Wei(self.w3.lido_contracts.withdrawal_queue_nft.functions.unfinalizedStETH().call(block_identifier=self.blockstamp.block_hash))
