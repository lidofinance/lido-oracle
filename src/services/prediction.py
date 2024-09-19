import logging

from web3.types import EventData, Wei

from src.modules.submodules.types import ChainConfig
from src.providers.execution.exceptions import InconsistentEvents
from src.types import ReferenceBlockStamp
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.events import get_events_in_past
from src.web3py.types import Web3


logger = logging.getLogger(__name__)


class RewardsPredictionService:
    """
    Based on events predicts amount of eth that protocol will earn per epoch.

    **Note** Withdraw amount in Oracle report is limited, so prediction shows not actual Lido rewards, but medium.
    amount of ETH that were withdrawn in Oracle reports.
    """
    def __init__(self, w3: Web3):
        self.w3 = w3

    @lru_cache(maxsize=1)
    def get_rewards_per_epoch(
        self,
        blockstamp: ReferenceBlockStamp,
        chain_configs: ChainConfig,
    ) -> Wei:
        prediction_duration_in_slots = self.w3.lido_contracts.oracle_daemon_config.prediction_duration_in_slots(blockstamp.block_hash)

        token_rebase_events = get_events_in_past(
            self.w3.lido_contracts.lido.events.TokenRebased,  # type: ignore[arg-type]
            blockstamp,
            prediction_duration_in_slots,
            chain_configs.seconds_per_slot,
            'reportTimestamp',
        )

        eth_distributed_events = get_events_in_past(
            self.w3.lido_contracts.lido.events.ETHDistributed,  # type: ignore[arg-type]
            blockstamp,
            prediction_duration_in_slots,
            chain_configs.seconds_per_slot,
            'reportTimestamp',
        )

        try:
            events = self._group_events_by_transaction_hash(token_rebase_events, eth_distributed_events)
        except InconsistentEvents as error:
            msg = (
                f'ETHDistributed and TokenRebased events from {self.w3.lido_contracts.lido.address} are inconsistent.'
                f'In each tx with ETHDistributed event should be one TokenRebased event.'
            )
            logger.error({'msg': msg, 'error': str(error)})
            raise InconsistentEvents(msg) from error

        if not events:
            return Wei(0)

        total_rewards = 0
        time_spent = 0
        for event in events:
            total_rewards += event['postCLBalance'] + event['withdrawalsWithdrawn'] - event['preCLBalance'] + event['executionLayerRewardsWithdrawn']
            time_spent += event['timeElapsed']

        return max(
            Wei(total_rewards * chain_configs.seconds_per_slot * chain_configs.slots_per_epoch // time_spent),
            Wei(0),
        )

    @staticmethod
    def _group_events_by_transaction_hash(event_type_1: list[EventData], event_type_2: list[EventData]):
        event_type_1_dict = {}

        for event in event_type_1:
            event_type_1_dict[event['transactionHash']] = event

        if len(event_type_1_dict.keys()) != len(event_type_1):
            raise InconsistentEvents('Events are inconsistent: some events from event_type_1 has same transactionHash.')

        result_event_data = []

        for event_2 in event_type_2:
            tx_hash = event_2['transactionHash']

            event_1 = event_type_1_dict.pop(event_2['transactionHash'], None)

            if not event_1:
                raise InconsistentEvents(f'Events are inconsistent: no events from type 1 with {tx_hash=}.')

            result_event_data.append({
                **event_1['args'],
                **event_2['args'],
            })

        if event_type_1_dict:
            raise InconsistentEvents('Events are inconsistent: unexpected events_type_1 amount.')

        return result_event_data
