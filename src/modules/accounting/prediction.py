import statistics
from typing import Iterable
from web3.contract import Contract
from web3.types import Wei, EventData
from src.typings import BlockStamp


class Prediction:
    _lidoContract: Contract

    def __init__(self, lido_contract: Contract):
        self._lidoContract = lido_contract

    def get_rewards_per_epoch(self,
                              blockstamp: BlockStamp,
                              percentile_el_rewards_bp,
                              percentile_cl_rewards_bp,
                              duration_in_slots: int,
                              slots_per_epoch: int = 32,
                              seconds_per_slot: int = 12,
                              ) -> Wei:
        ## TODO: For future where to get and pass variables into get_rewards_per_epoch
        ## duration_in_slots: int = self.w3.eth.OracleDaemonConfig.functions.get('durationInSlots').call()
        ## slots_per_epoch, seconds_per_slot, genesis_time = self.w3.eth.HashConsensus.functions.getChainConfig().call()

        from_block, to_block = self.get_block_interval(
            ref_block=blockstamp['block_number'],
            duration_in_slots=duration_in_slots,
        )

        left_block_timestamp = blockstamp['block_timestamp'] - duration_in_slots * seconds_per_slot

        ETHDistributed_events = self.get_ETHDistributed_events(from_block, to_block, left_block_timestamp)
        TokenRebased_events = self.get_TokenRebased_events(from_block, to_block, left_block_timestamp)

        trx_hashes = ETHDistributed_events.keys()
        if not trx_hashes or trx_hashes != TokenRebased_events.keys():
            raise Exception("ETHDistributed, TokenRebased are not not consistent")

        rewards_cl_speed, rewards_exe_speed = [], []
        for h in trx_hashes:
            rewards_cl_speed.append(
                ETHDistributed_events[h]['withdrawalsWithdrawn'] // TokenRebased_events[h]['timeElapsed'])
            rewards_exe_speed.append(
                ETHDistributed_events[h]['executionLayerRewardsWithdrawn'] // TokenRebased_events[h]['timeElapsed'])

        median_rewards_cl_speed = self.percentile(rewards_cl_speed, percentile_cl_rewards_bp)
        median_rewards_exe_speed = self.percentile(rewards_exe_speed, percentile_el_rewards_bp)
        rewards = median_rewards_cl_speed + median_rewards_exe_speed

        return Wei(rewards * slots_per_epoch * seconds_per_slot)

    @staticmethod
    def get_block_interval(ref_block: int, duration_in_slots: int) -> (int, int):
        from_block = ref_block - duration_in_slots
        to_block = ref_block
        return int(from_block), to_block

    def get_ETHDistributed_events(self, from_block, to_block, events_gte_timestamp):
        events: Iterable[EventData] = self._lidoContract.events.ETHDistributed.get_logs(
            from_block=from_block,
            to_block=to_block,
        )

        if events:
            return self.group_event_by_transaction_hash(events, events_gte_timestamp)

        return None

    def get_TokenRebased_events(self, from_block, to_block, events_gte_timestamp):
        events: Iterable[EventData] = self._lidoContract.events.TokenRebased.get_logs(
            from_block=from_block,
            to_block=to_block,
        )

        if events:
            return self.group_event_by_transaction_hash(events, events_gte_timestamp)

        return None

    @staticmethod
    def group_event_by_transaction_hash(events: [], events_gte_timestamp):
        result = {}
        for event in events:
            if event['args']['reportTimestamp'] >= events_gte_timestamp:
                result[event['transactionHash']] = event['args']

        return result

    @staticmethod
    def percentile(data, basis_point):
        percentile = basis_point * 0.0001
        sorted_data = sorted(data)
        index = (len(sorted_data) - 1) * percentile
        if index.is_integer():
            return sorted_data[int(index)]
        else:
            floor_value = sorted_data[int(index)]
            ceil_value = sorted_data[int(index) + 1]
            return (ceil_value - floor_value) * (index - int(index)) + floor_value
