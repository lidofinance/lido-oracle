import logging
from typing import Iterator

from eth_typing import BlockNumber
from web3.contract.contract import ContractEvent
from web3.types import EventData

from src import variables
from src.providers.execution.exceptions import InconsistentEvents
from src.types import ReferenceBlockStamp

logger = logging.getLogger(__name__)


def get_events_in_past(
    contract_event: ContractEvent,
    to_blockstamp: ReferenceBlockStamp,
    for_slots: int,
    seconds_per_slot: int,
    timestamp_field_name: str = 'timestamp',
):
    """
    This is protection against missed slots when between 10 and 11 block number could be 5 missed slots.
    Events should contain Timestamp field.
    """
    #   [ ] - slot
    #   [x] - slot with existed block
    #   [o] - slot with missed block
    #    e  - event
    #
    #   for_slots = 10 (for example)
    #   ref_slot = 22
    #   block_number = 13
    #
    # ref_slot_shift = 22 - 18
    # for_slots_without_missed_blocks = 10 - 4
    #
    #                  [--------------- Event search block period -------------]
    #                                                  (---- Needed events --------------------]
    #              from_block                      timeout_border            to_block       ref_slot
    #                  |                               |                       |               |
    #      e           e   e       e           e       e       e           e   e               v   e   e
    #   --[x]-[o]-[x]-[x]-[x]-[x]-[x]-[o]-[o]-[x]-[x]-[x]-[o]-[x]-[x]-[o]-[x]-[x]-[o]-[o]-[o]-[o]-[x]-[x]----> time
    #      1   2   3   4   5   6   7   8   9  10  11  12  13  14  15  16  17  18  19  20  21  22  23  24       slot
    #      1   -   2   3   4   5   6   -   -   7   8   9   -  10  11   -  12  13   -   -   -   -  14  15       block
    #
    #   So we should consider events from blocks [10, 12, 13]
    ref_slot_shift = to_blockstamp.ref_slot - to_blockstamp.slot_number
    for_slots_without_missed_blocks = for_slots - ref_slot_shift

    if for_slots_without_missed_blocks <= 0:
        # No non-missed slots in current search period
        return []

    from_block = max(0, to_blockstamp.block_number - for_slots_without_missed_blocks)
    from_timestamp = to_blockstamp.block_timestamp - for_slots_without_missed_blocks * seconds_per_slot

    events = get_events_in_range(
        contract_event,
        l_block=BlockNumber(from_block),
        r_block=BlockNumber(to_blockstamp.block_number),
    )

    return [event for event in events if event['args'][timestamp_field_name] > from_timestamp]


def get_events_in_range(event: ContractEvent, l_block: BlockNumber, r_block: BlockNumber) -> Iterator[EventData]:
    """Fetch all the events in the given blocks range (closed interval)"""

    if l_block > r_block:
        raise ValueError(f"{l_block=} > {r_block=}")

    while True:
        to_block = min(r_block, BlockNumber(l_block + variables.EVENTS_SEARCH_STEP))

        logger.info({"msg": f"Fetching {event.event_name} events in range [{l_block}:{to_block}]"})

        for e in event.get_logs(from_block=l_block, to_block=to_block):
            if not l_block <= e["blockNumber"] <= to_block:
                raise InconsistentEvents
            yield e

        if to_block == r_block:
            break

        l_block = BlockNumber(to_block + 1)
