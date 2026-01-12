from web3.types import Wei

from src.metrics.prometheus.business import CONTRACT_ON_PAUSE
from src.variables import FINALIZATION_BATCH_MAX_REQUEST_COUNT
from src.web3py.types import Web3
from src.types import ReferenceBlockStamp, FinalizationBatches
from src.services.safe_border import SafeBorder
from src.modules.submodules.consensus import ChainConfig, FrameConfig
from src.modules.accounting.types import BatchState


class Withdrawal:
    """
    Service calculates which withdrawal requests should be finalized using next factors:

    1. Safe border epoch for the current reference slot.
    2. The amount of available ETH is determined from the Withdrawal Vault, EL Vault, and buffered ETH.
    """
    def __init__(
        self,
        w3: Web3,
        blockstamp: ReferenceBlockStamp,
        chain_config: ChainConfig,
        frame_config: FrameConfig,
    ) -> None:
        self.w3 = w3
        self.safe_border_service = SafeBorder(self.w3, blockstamp, chain_config, frame_config)

        self.chain_config = chain_config
        self.frame_config = frame_config
        self.blockstamp = blockstamp

    def get_finalization_batches(
        self,
        is_bunker_mode: bool,
        share_rate: int,
        withdrawal_vault_balance: Wei,
        el_rewards_vault_balance: Wei
    ) -> FinalizationBatches:
        on_pause = self.w3.lido_contracts.withdrawal_queue_nft.is_paused(self.blockstamp.block_hash)
        CONTRACT_ON_PAUSE.labels('finalization').set(on_pause)

        if on_pause:
            return FinalizationBatches([])

        if not self._has_unfinalized_requests():
            return FinalizationBatches([])

        available_eth = self._get_available_eth(withdrawal_vault_balance, el_rewards_vault_balance)

        if not available_eth:
            return FinalizationBatches([])

        withdrawable_until_epoch = self.safe_border_service.get_safe_border_epoch(is_bunker_mode)
        withdrawable_until_timestamp = (
                self.chain_config.genesis_time + (
                    withdrawable_until_epoch * self.chain_config.slots_per_epoch * self.chain_config.seconds_per_slot
            )
        )

        return FinalizationBatches(self._calculate_finalization_batches(share_rate, available_eth, withdrawable_until_timestamp))

    def _has_unfinalized_requests(self) -> bool:
        last_finalized_id = self.w3.lido_contracts.withdrawal_queue_nft.get_last_finalized_request_id(self.blockstamp.block_hash)
        last_requested_id = self.w3.lido_contracts.withdrawal_queue_nft.get_last_request_id(self.blockstamp.block_hash)

        return last_finalized_id < last_requested_id

    def _get_available_eth(self, withdrawal_vault_balance: Wei, el_rewards_vault_balance: Wei) -> Wei:
        buffered_ether = self.w3.lido_contracts.lido.get_buffered_ether(self.blockstamp.block_hash)

        # This amount of eth could not be spent for deposits.
        unfinalized_steth = self.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth(self.blockstamp.block_hash)

        reserved_buffer = min(buffered_ether, unfinalized_steth)

        return Wei(withdrawal_vault_balance + el_rewards_vault_balance + reserved_buffer)

    def _calculate_finalization_batches(
        self,
        share_rate: int,
        available_eth: int,
        until_timestamp: int
    ) -> list[int]:
        max_length = self.w3.lido_contracts.withdrawal_queue_nft.max_batches_length(self.blockstamp.block_hash)

        state = BatchState(
            remaining_eth_budget=available_eth,
            finished=False,
            batches=list([0] * max_length),
            batches_length=0
        )

        while not state.finished:
            state = self.w3.lido_contracts.withdrawal_queue_nft.calculate_finalization_batches(
                share_rate,
                until_timestamp,
                FINALIZATION_BATCH_MAX_REQUEST_COUNT,
                state.as_tuple(),
                self.blockstamp.block_hash,
            )

        return list(filter(lambda value: value > 0, state.batches))
