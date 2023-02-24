import logging

from web3.types import Wei, EventData

from src.modules.submodules.typings import ChainConfig
from src.typings import BlockStamp
from src.utils.events import get_events_in_past
from src.web3py.typings import Web3


logger = logging.getLogger(__name__)


class RewardsPredictionService:
    def __init__(self, w3: Web3):
        self.w3 = w3

    def get_rewards_per_epoch(
            self,
            blockstamp: BlockStamp,
            chain_configs: ChainConfig,
    ) -> Wei:
        prediction_frame_in_slots = Web3.to_int(
            self.w3.lido_contracts.oracle_daemon_config.functions.get('PREDICTION_DURATION_IN_SLOTS').call(
                block_identifier=blockstamp.block_hash,
            )
        )
        logger.info({'msg': 'Fetch prediction frame in slots.', 'value': prediction_frame_in_slots})

        token_rebase_events = get_events_in_past(
            self.w3.lido_contracts.lido.events.TokenRebased,
            blockstamp,
            prediction_frame_in_slots,
            chain_configs.seconds_per_slot,
            'reportTimestamp',
        )

        eth_distributed_events = get_events_in_past(
            self.w3.lido_contracts.lido.events.ETHDistributed,
            blockstamp,
            prediction_frame_in_slots,
            chain_configs.seconds_per_slot,
            'reportTimestamp',
        )

        events = self._group_events_by_transaction_hash(token_rebase_events, eth_distributed_events)

        total_rewards = 0
        time_spent = 0
        for event in events:
            total_rewards += event['withdrawalsWithdrawn'] + event['executionLayerRewardsWithdrawn']
            time_spent += event['timeElapsed']

        return total_rewards * chain_configs.slots_per_epoch * chain_configs.seconds_per_slot / total_rewards

    @staticmethod
    def _group_events_by_transaction_hash(event_type_1: list[EventData], event_type_2: list[EventData]):
        result_event_data = []

        for event_1 in event_type_1:
            for event_2 in event_type_2:
                if event_2['transactionHash'] == event_1['transactionHash']:
                    result_event_data.append({
                        **event_1['args'],
                        **event_2['args'],
                    })
                    break

        return result_event_data
