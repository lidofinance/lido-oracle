import json
import logging
from itertools import groupby
from typing import Callable, Iterable, cast

from eth_typing.evm import ChecksumAddress
from web3.contract.contract import Contract, ContractEvent
from web3.types import BlockIdentifier, EventData

from src import variables

logger = logging.getLogger(__name__)


class CSModule(Contract):
    abi_path = "./assets/CSModule.json"

    # TODO: Inherit from the base class.
    def __init__(self, address: ChecksumAddress | None = None) -> None:
        with open(self.abi_path, encoding="utf-8") as f:
            self.abi = json.load(f)
        super().__init__(address)

    def get_stuck_node_operators(self, l_block: BlockIdentifier, r_block: BlockIdentifier) -> Iterable:
        """Returns node operators assumed to be stuck for the given frame (defined by the blockstamps)"""

        l_block_number = int(self.w3.eth.get_block(l_block)["number"])  # type: ignore

        by_no_id: Callable[[EventData], int] = lambda e: int(
            e["args"]["nodeOperatorId"]
        )  # TODO: Maybe it's int already?

        events = sorted(self.get_stuck_keys_events(r_block), key=by_no_id)
        for no_id, group in groupby(events, key=by_no_id):
            last_event = sorted(tuple(group), key=lambda e: e["blockNumber"])[-1]
            # Operators unstucked at the very beginning of the frame are fine.
            if (
                last_event["args"]["stuckValidatorsCount"] == 0 and
                last_event["blockNumber"] <= l_block_number
            ):
                continue

            yield no_id

    def get_stuck_keys_events(self, block: BlockIdentifier) -> Iterable[EventData]:
        """Fetch all the StuckSigningKeysCountChanged events up to the given block (closed interval)"""

        r_block = int(self.w3.eth.get_block(block)["number"])  # type: ignore
        l_block = r_block - variables.EVENTS_SEARCH_STEP
        l_block = 0 if l_block < 0 else l_block

        while l_block >= 0:
            for e in cast(ContractEvent, self.events.StuckSigningKeysCountChanged).get_logs(
                fromBlock=l_block, toBlock=r_block
            ):
                yield e

            if not self.is_deployed(l_block):
                break

            r_block = l_block - 1
            l_block = r_block - variables.EVENTS_SEARCH_STEP

    def is_deployed(self, block: BlockIdentifier) -> bool:
        return self.w3.eth.get_code(self.address, block_identifier=block) != b""
