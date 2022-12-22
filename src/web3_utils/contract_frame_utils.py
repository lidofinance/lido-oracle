import logging

from hexbytes import HexBytes
from web3 import Web3
from web3.contract import Contract

from src.web3_utils.typings import SlotNumber


logger = logging.getLogger(__name__)


def is_current_epoch_reportable(
    w3: Web3,
    contract: Contract,
    slot: SlotNumber,
    block_hash: HexBytes,
):
    last_reportable_epoch = get_latest_reportable_epoch(contract, slot, block_hash)
    logging.info({'msg': f'Get latest reportable epoch.', 'value': last_reportable_epoch})

    last_reported_epoch = get_last_reported_epoch(w3, contract, block_hash)
    logging.info({'msg': f'Get last reported epoch.', 'value': last_reported_epoch})

    return last_reported_epoch < last_reportable_epoch


def get_last_reported_epoch(w3: Web3, contract: Contract, block_hash: HexBytes) -> int:
    block = w3.eth.getBlock(block_hash)

    epochs_per_frame, slots_per_epoch, _, _ = contract.functions.getBeaconSpec().call(block_identifier=block_hash)

    from_block = block.number - slots_per_epoch * epochs_per_frame * 2

    # One day step
    step = (epochs_per_frame + 1) * slots_per_epoch

    # Try to fetch and parse last 'Completed' event from the contract.
    for end in range(block.number, from_block, -step):
        start = max(end - step + 1, from_block)

        events = contract.events.ConsensusReached.getLogs(fromBlock=start, toBlock=end)

        if events:
            event = events[-1]
            return event['args']['epochId']

    return 0


def get_latest_reportable_epoch(contract: Contract, slot: SlotNumber, block_hash: HexBytes) -> int:
    epochs_per_frame, slots_per_epoch, _, _ = contract.functions.getBeaconSpec().call(block_identifier=block_hash)

    potentially_reportable_epoch = contract.functions.getCurrentFrame().call(block_identifier=block_hash)[0]

    return min(
        potentially_reportable_epoch, (slot / slots_per_epoch // epochs_per_frame) * epochs_per_frame
    )
