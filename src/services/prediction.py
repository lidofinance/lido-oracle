import logging

from web3.types import Wei, EventData

from src.modules.submodules.typings import ChainConfig
from src.typings import ReferenceBlockStamp
from src.utils.events import get_events_in_past
from src.web3py.typings import Web3


logger = logging.getLogger(__name__)


class RewardsPredictionService:
    def __init__(self, w3: Web3):
        self.w3 = w3

    def get_rewards_per_epoch(
        self,
        blockstamp: ReferenceBlockStamp,
        chain_configs: ChainConfig,
    ) -> Wei:
        prediction_duration_in_slots = self._get_prediction_duration_in_slots(blockstamp)
        logger.info({'msg': 'Fetch prediction frame in slots.', 'value': prediction_duration_in_slots})

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

        events = self._group_events_by_transaction_hash(token_rebase_events, eth_distributed_events)

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
        result_event_data = []

        for event_1 in event_type_1:
            for event_2 in event_type_2:
                if event_2['transactionHash'] == event_1['transactionHash']:
                    result_event_data.append({
                        **event_1['args'],
                        **event_2['args'],
                    })
                    break

        if len(event_type_1) == len(event_type_2) == len(result_event_data):
            return result_event_data

        raise ValueError(
            f"Events are inconsistent: {len(event_type_1)=}, {len(event_type_2)=}, {len(result_event_data)=}"
        )

    def _get_prediction_duration_in_slots(self, blockstamp: ReferenceBlockStamp) -> int:
        return Web3.to_int(
            self.w3.lido_contracts.oracle_daemon_config.functions.get('PREDICTION_DURATION_IN_SLOTS').call(
                block_identifier=blockstamp.block_hash,
            )
        )
