"""
Line-by-line model of WithdrawalQueueBase: calculateFinalizationBatches, prefinalize and the per-request claim.
The tests check batches against what the contract locks and pays out, not against the oracle's own arithmetic.
"""

from dataclasses import dataclass

from src.modules.oracles.accounting.types import BatchState, WithdrawalRequestStatus


E27 = 10**27
MAX_BATCHES_LENGTH = 36


@dataclass
class _Request:
    cumulative_steth: int
    cumulative_shares: int
    report_timestamp: int


class WithdrawalQueueModel:
    def __init__(self) -> None:
        self.queue = [_Request(0, 0, 0)]
        self.report_timestamp = 0

    def on_oracle_report(self, report_timestamp: int) -> None:
        self.report_timestamp = report_timestamp

    def request(self, steth: int, total_pooled_ether: int, total_shares: int) -> None:
        shares = steth * total_shares // total_pooled_ether
        last = self.queue[-1]
        self.queue.append(
            _Request(last.cumulative_steth + steth, last.cumulative_shares + shares, self.report_timestamp)
        )

    def _calc_batch(self, pre_start: _Request, end: _Request) -> tuple[int, int, int]:
        steth = end.cumulative_steth - pre_start.cumulative_steth
        shares = end.cumulative_shares - pre_start.cumulative_shares
        return steth * E27 // shares, steth, shares

    def get_last_finalized_request_id(self, _block) -> int:
        return 0

    def get_last_request_id(self, _block) -> int:
        return len(self.queue) - 1

    def max_batches_length(self, _block) -> int:
        return MAX_BATCHES_LENGTH

    def calculate_finalization_batches(self, max_share_rate, _max_timestamp, max_requests, state_tuple, _block):
        remaining, _, batches, batches_length = state_tuple
        batches = list(batches)
        prev_rate = 0
        if batches_length == 0:
            current_id = self.get_last_finalized_request_id(None) + 1
            prev = self.queue[current_id - 1]
        else:
            last_handled = batches[batches_length - 1]
            current_id = last_handled + 1
            prev = self.queue[last_handled]
            prev_rate, _, _ = self._calc_batch(self.queue[last_handled - 1], prev)

        next_call_id = current_id + max_requests
        queue_length = len(self.queue)
        while current_id < queue_length and current_id < next_call_id:
            request = self.queue[current_id]
            rate, eth, shares = self._calc_batch(prev, request)
            if rate > max_share_rate:
                eth = shares * max_share_rate // E27
            if eth > remaining:
                break
            remaining -= eth

            if batches_length != 0 and (
                prev.report_timestamp == request.report_timestamp
                or (prev_rate <= max_share_rate and rate <= max_share_rate)
                or (prev_rate > max_share_rate and rate > max_share_rate)
            ):
                batches[batches_length - 1] = current_id
            else:
                if batches_length == MAX_BATCHES_LENGTH:
                    break
                batches[batches_length] = current_id
                batches_length += 1

            prev_rate = rate
            prev = request
            current_id += 1

        finished = current_id == queue_length or current_id < next_call_id
        return BatchState(remaining, finished, batches, batches_length)

    def prefinalize(self, batches, max_share_rate, _block) -> int:
        eth_to_lock = 0
        prev = self.queue[self.get_last_finalized_request_id(None)]
        for batch_end in batches:
            end = self.queue[batch_end]
            rate, steth, shares = self._calc_batch(prev, end)
            eth_to_lock += shares * max_share_rate // E27 if rate > max_share_rate else steth
            prev = end
        return eth_to_lock

    def claimable(self, request_id: int, max_share_rate: int) -> int:
        rate, eth, shares = self._calc_batch(self.queue[request_id - 1], self.queue[request_id])
        return shares * max_share_rate // E27 if rate > max_share_rate else eth

    def get_withdrawal_statuses(self, request_ids, _block) -> list[WithdrawalRequestStatus]:
        statuses = []
        for request_id in request_ids:
            _, steth, shares = self._calc_batch(self.queue[request_id - 1], self.queue[request_id])
            statuses.append(WithdrawalRequestStatus(steth, shares, '0x0', 0, False, False))
        return statuses
