import json
import logging
from itertools import groupby
from typing import Callable, Iterable, cast

from eth_typing import BlockNumber, ChecksumAddress
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

        l_block_number = self.w3.eth.get_block(l_block).get("number", BlockNumber(0))
        r_block_number = self.w3.eth.get_block(r_block).get("number", BlockNumber(0))
        assert l_block_number <= r_block_number

        by_no_id: Callable[[EventData], int] = lambda e: int(
            e["args"]["nodeOperatorId"]
        )  # TODO: Maybe it's int already?

        events = sorted(self.get_stuck_keys_events(r_block_number), key=by_no_id)
        for no_id, group in groupby(events, key=by_no_id):
            last_event = sorted(tuple(group), key=lambda e: e["blockNumber"])[-1]
            # Operators unstucked at the very beginning of the frame are fine.
            if (
                last_event["args"]["stuckValidatorsCount"] == 0 and
                last_event["blockNumber"] <= l_block_number
            ):
                continue

            yield no_id

    # TODO: Make a cache for the events?
    def get_stuck_keys_events(self, r_block: BlockNumber) -> Iterable[EventData]:
        """Fetch all the StuckSigningKeysCountChanged events up to the given block (closed interval)"""

        l_block = BlockNumber(r_block - variables.EVENTS_SEARCH_STEP)
        l_block = BlockNumber(0) if l_block < 0 else l_block

        while l_block >= 0:
            logger.info({"msg": f"Fetching stuck node operators events in range [{l_block};{r_block}]"})

            for e in cast(ContractEvent, self.events.StuckSigningKeysCountChanged).get_logs(
                fromBlock=l_block, toBlock=r_block
            ):
                yield e

            if not self.is_deployed(l_block):
                break

            r_block = BlockNumber(l_block - 1)
            l_block = BlockNumber(r_block - variables.EVENTS_SEARCH_STEP)

    # TODO: Move to a base contract class.
    def is_deployed(self, block: BlockIdentifier) -> bool:
        logger.info({"msg": f"Check that the contract {self.__class__.__name__} id deployed at {block=}"})
        return self.w3.eth.get_code(self.address, block_identifier=block) != b""

    def is_paused(self, block: BlockIdentifier = "latest") -> bool:
        resp = self.functions.isPaused().call(block_identifier=block)
        logger.debug(
            {
                "msg": "Call to isPaused()",
                "value": resp,
                "block_identifier": repr(block),
            }
        )
        return resp
