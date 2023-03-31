from web3.types import Wei

from src.metrics.prometheus.business import CONTRACT_ON_PAUSE
from src.variables import FINALIZATION_BATCH_MAX_REQUEST_COUNT
from src.utils.abi import named_tuple_to_dataclass
from src.web3py.typings import Web3
from src.typings import ReferenceBlockStamp
from src.services.safe_border import SafeBorder
from src.modules.submodules.consensus import ChainConfig, FrameConfig
from src.modules.accounting.typings import BatchState


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
    ) -> list[int]:
        on_pause = self._is_requests_finalization_paused()
        CONTRACT_ON_PAUSE.set(on_pause)
        if on_pause:
            return []

        if not self._has_unfinalized_requests():
            return []

        withdrawable_until_epoch = self.safe_border_service.get_safe_border_epoch(is_bunker_mode)
        withdrawable_until_timestamp = (
                self.chain_config.genesis_time + (
                    withdrawable_until_epoch * self.chain_config.slots_per_epoch * self.chain_config.seconds_per_slot
            )
        )
        available_eth = self._get_available_eth(withdrawal_vault_balance, el_rewards_vault_balance)

        return self._calculate_finalization_batches(share_rate, available_eth, withdrawable_until_timestamp)

    def _has_unfinalized_requests(self) -> bool:
        last_finalized_id = self._fetch_last_finalized_request_id()
        last_requested_id = self._fetch_last_request_id()

        return last_finalized_id < last_requested_id

    def _get_available_eth(self, withdrawal_vault_balance: Wei, el_rewards_vault_balance: Wei) -> Wei:
        buffered_ether = self._fetch_buffered_ether()
        # This amount of eth could not be spent for deposits.
        unfinalized_steth = self._fetch_unfinalized_steth()

        reserved_buffer = min(buffered_ether, unfinalized_steth)

        return Wei(withdrawal_vault_balance + el_rewards_vault_balance + reserved_buffer)

    def _calculate_finalization_batches(
        self, share_rate: int, available_eth: int, until_timestamp: int
    ) -> list[int]:
        state = BatchState(
            remaining_eth_budget=available_eth,
            finished=False,
            batches=[0] * self._fetch_max_batches_length(),
            batches_length=0
        )

        while not state.finished:
            state = self._fetch_finalization_batches(
                share_rate,
                until_timestamp,
                state
            )

        return list(filter(lambda value: value > 0, state.batches))

    def _fetch_last_finalized_request_id(self) -> int:
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.getLastFinalizedRequestId().call(
            block_identifier=self.blockstamp.block_hash
        )

    def _fetch_last_request_id(self) -> int:
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.getLastRequestId().call(
            block_identifier=self.blockstamp.block_hash
        )

    def _fetch_buffered_ether(self) -> Wei:
        return Wei(self.w3.lido_contracts.lido.functions.getBufferedEther().call(
            block_identifier=self.blockstamp.block_hash
        ))

    def _fetch_unfinalized_steth(self) -> Wei:
        return Wei(self.w3.lido_contracts.withdrawal_queue_nft.functions.unfinalizedStETH().call(
            block_identifier=self.blockstamp.block_hash
        ))

    def _is_requests_finalization_paused(self) -> bool:
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.isPaused().call(
            block_identifier=self.blockstamp.block_hash
        )

    def _fetch_max_batches_length(self) -> int:
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.MAX_BATCHES_LENGTH().call(
            block_identifier=self.blockstamp.block_hash
        )

    def _fetch_finalization_batches(self, share_rate: int, timestamp: int, batch_state: BatchState) -> BatchState:
        return named_tuple_to_dataclass(
            self.w3.lido_contracts.withdrawal_queue_nft.functions.calculateFinalizationBatches(
                share_rate,
                timestamp,
                FINALIZATION_BATCH_MAX_REQUEST_COUNT,
                batch_state.as_tuple()
            ).call(block_identifier=self.blockstamp.block_hash),
            BatchState
        )
