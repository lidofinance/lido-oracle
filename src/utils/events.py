from web3.contract.contract import ContractEvent

from src.typings import BlockStamp


def get_events_in_past(contract_event: ContractEvent, to_blockstamp: BlockStamp, for_slots: int, seconds_per_slot: int):
    """
        This is protection against missed slots. When between 10 and 11 block number could be 5 missed slots.
        To filter events with this method Events should contain timestamp inside args.
    """
    from_block = to_blockstamp.block_number - for_slots
    from_timestamp = to_blockstamp.block_timestamp - for_slots * seconds_per_slot

    events = contract_event.get_logs(
        fromBlock=from_block,
        toBlock=to_blockstamp.block_number,
    )

    return [event for event in events if event['args']['timestamp'] >= from_timestamp]
