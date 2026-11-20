import logging
from itertools import batched

from web3.types import Wei

from src.constants import SHARE_RATE_PRECISION_E27
from src.metrics.prometheus.business import CONTRACT_ON_PAUSE
from src.modules.oracles.accounting.types import BatchState, WithdrawalRequestStatus
from src.modules.oracles.common.consensus import ChainConfig, FrameConfig
from src.services.safe_border import SafeBorder
from src.types import FinalizationBatches, ReferenceBlockStamp
from src.variables import FINALIZATION_BATCH_MAX_REQUEST_COUNT
from src.web3py.types import Web3


logger = logging.getLogger(__name__)

# The queue locks a batch at its aggregate share rate and pays each claim at the request's own rate, so even
# a well-formed batch locks a few wei more than its claims: floor(sum(shares) * rate) against
# sum(floor(shares_i * rate)), or a request one rounding step above the rate in a nominal batch.
ROUNDING_WEI_PER_REQUEST = 2


class Withdrawal:
    """
    Service calculates which withdrawal requests should be finalized using the next factors:

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
        self, is_bunker_mode: bool, share_rate: int, withdrawal_vault_balance: Wei, el_rewards_vault_balance: Wei
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
        withdrawable_until_timestamp = self.chain_config.genesis_time + (
            withdrawable_until_epoch * self.chain_config.slots_per_epoch * self.chain_config.seconds_per_slot
        )

        return FinalizationBatches(
            self._calculate_finalization_batches(share_rate, available_eth, withdrawable_until_timestamp)
        )

    def _has_unfinalized_requests(self) -> bool:
        last_finalized_id = self.w3.lido_contracts.withdrawal_queue_nft.get_last_finalized_request_id(
            self.blockstamp.block_hash
        )
        last_requested_id = self.w3.lido_contracts.withdrawal_queue_nft.get_last_request_id(self.blockstamp.block_hash)

        return last_finalized_id < last_requested_id

    def _get_available_eth(self, withdrawal_vault_balance: Wei, el_rewards_vault_balance: Wei) -> Wei:
        withdrawals_reserve = self.w3.lido_contracts.lido.get_withdrawals_reserve(self.blockstamp.block_hash)

        # This amount of eth could not be spent for deposits.
        unfinalized_steth = self.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth(self.blockstamp.block_hash)

        reserved_withdrawals_eth = min(withdrawals_reserve, unfinalized_steth)

        return Wei(withdrawal_vault_balance + el_rewards_vault_balance + reserved_withdrawals_eth)

    def _calculate_finalization_batches(self, share_rate: int, available_eth: int, until_timestamp: int) -> list[int]:
        """
        `calculateFinalizationBatches` debits the budget per request, while `prefinalize` locks each batch at its
        aggregate rate. The budget is cut by the worst-case rounding so the lock never exceeds the ether the
        report has. A batch that mixes discounted and nominal requests locks far more than its claims pay out,
        and the excess stays on the queue for good, so such batches are split.
        """
        withdrawal_queue = self.w3.lido_contracts.withdrawal_queue_nft
        block_hash = self.blockstamp.block_hash

        last_finalized_id = withdrawal_queue.get_last_finalized_request_id(block_hash)
        unfinalized_count = withdrawal_queue.get_last_request_id(block_hash) - last_finalized_id
        budget = available_eth - ROUNDING_WEI_PER_REQUEST * unfinalized_count
        if budget <= 0:
            return []

        max_length = withdrawal_queue.max_batches_length(block_hash)

        state = BatchState(
            remaining_eth_budget=budget, finished=False, batches=list([0] * max_length), batches_length=0
        )

        while not state.finished and state.remaining_eth_budget > 0:
            state = withdrawal_queue.calculate_finalization_batches(
                share_rate,
                until_timestamp,
                FINALIZATION_BATCH_MAX_REQUEST_COUNT,
                state.as_tuple(),
                block_hash,
            )

        batches = list(filter(lambda value: value > 0, state.batches))
        if not batches:
            return []

        # With all batch slots taken the queue debits the next request before it finds no room for it,
        # so the debited budget covers a request outside the batches and cannot tell whether they are mixed.
        if state.batches_length < max_length:
            claims = budget - state.remaining_eth_budget
            eth_to_lock = withdrawal_queue.prefinalize(batches, share_rate, block_hash)
            if eth_to_lock - claims <= ROUNDING_WEI_PER_REQUEST * (batches[-1] - last_finalized_id):
                return batches

            logger.warning(
                {
                    'msg': 'Finalization batches lock more than their requests claim. Splitting mixed batches.',
                    'batches': batches,
                    'eth_to_lock': eth_to_lock,
                    'claims': claims,
                }
            )
        return self._split_mixed_batches(batches, share_rate, last_finalized_id, max_length)

    def _split_mixed_batches(
        self, batches: list[int], share_rate: int, last_finalized_id: int, max_length: int
    ) -> list[int]:
        """Ends a batch also wherever neighbouring requests fall on different sides of the share rate."""
        request_ids = range(last_finalized_id + 1, batches[-1] + 1)
        discounted = [
            _is_discounted(status.amount_of_st_eth, status.amount_of_shares, share_rate)
            for status in self._get_withdrawal_statuses(list(request_ids))
        ]
        batch_ends = set(batches)
        result = [
            request_id
            for index, request_id in enumerate(request_ids)
            if request_id in batch_ends or discounted[index] != discounted[index + 1]
        ]
        return result[:max_length]

    def _get_withdrawal_statuses(self, request_ids: list[int]) -> list[WithdrawalRequestStatus]:
        return [
            status
            for chunk in batched(request_ids, FINALIZATION_BATCH_MAX_REQUEST_COUNT, strict=False)
            for status in self.w3.lido_contracts.withdrawal_queue_nft.get_withdrawal_statuses(
                list(chunk), self.blockstamp.block_hash
            )
        ]


def _is_discounted(steth: int, shares: int, share_rate: int) -> bool:
    return steth * SHARE_RATE_PRECISION_E27 // shares > share_rate
