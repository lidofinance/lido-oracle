import logging
from collections.abc import Iterator

from eth_typing import BlockNumber
from web3.contract.contract import ContractEvent
from web3.types import EventData

from src import variables
from src.modules.common.types import ChainConfig
from src.providers.execution.exceptions import InconsistentEvents
from src.types import ReferenceBlockStamp


logger = logging.getLogger(__name__)


def get_events_in_past(
    contract_event: ContractEvent,
    to_blockstamp: ReferenceBlockStamp,
    for_slots: int,
    chain_config: ChainConfig,
    timestamp_field_name: str = 'timestamp',
):
    """
    Events emitted in the `for_slots` slots preceding the report's reference slot.

    The cutoff is the reference slot's own time, so it does not depend on which block the blockstamp
    physically stands on: pre-EIP-7732 that is the last non-missed slot at or before `ref_slot`,
    after it the reference slot's child. Events carry timestamps on the same grid — the accounting
    report timestamp is `GENESIS_TIME + refSlot * SECONDS_PER_SLOT` on the contract side, and an
    execution block's timestamp is its own slot's.

    The block range is only a coarse pre-filter for the node query. Execution blocks advance at most
    once per slot, so stepping back as many blocks as there are slots in the window always reaches
    past the cutoff; the timestamp comparison below is what actually bounds the result.

    Events should contain a timestamp field.
    """
    from_timestamp = chain_config.genesis_time + (to_blockstamp.ref_slot - for_slots) * chain_config.seconds_per_slot

    if to_blockstamp.block_timestamp <= from_timestamp:
        # The execution anchor is already at or before the cutoff, so no event can qualify
        return []

    slots_to_cover = (to_blockstamp.block_timestamp - from_timestamp) // chain_config.seconds_per_slot
    from_block = max(0, to_blockstamp.block_number - slots_to_cover)

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
