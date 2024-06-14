import logging
from itertools import groupby
from typing import Callable, Iterable, NamedTuple, cast

from eth_typing import BlockNumber
from web3.contract.contract import ContractEvent
from web3.types import BlockIdentifier, EventData

from src.providers.execution.exceptions import InconsistentEvents
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.events import get_events_in_range
from src.web3py.extensions.lido_validators import NodeOperatorId

from ..base_interface import ContractInterface

logger = logging.getLogger(__name__)


# TODO: Move to types?
class NodeOperatorSummary(NamedTuple):
    """getNodeOperatorSummary response, @see IStakingModule.sol"""

    targetLimitMode: int
    targetValidatorsCount: int
    stuckValidatorsCount: int
    refundedValidatorsCount: int
    stuckPenaltyEndTimestamp: int
    totalExitedValidators: int
    totalDepositedValidators: int
    depositableValidatorsCount: int


class CSModuleContract(ContractInterface):
    abi_path = "./assets/CSModule.json"

    MAX_OPERATORS_COUNT = 2**64

    @lru_cache(maxsize=1)
    def get_stuck_operators_ids(self, block: BlockIdentifier = "latest") -> Iterable[NodeOperatorId]:
        if not self.is_deployed(block):
            return

        # TODO: Check performance on a large amount of node operators in a module.
        for no_id in self.node_operators_ids(block):
            if self.node_operator_summary(no_id, block).stuckValidatorsCount > 0:
                yield no_id

    def new_stuck_operators_ids(self, l_block: BlockIdentifier, r_block: BlockIdentifier) -> Iterable[NodeOperatorId]:
        """Returns node operators assumed to be stuck for the given frame (defined by the block identifiers)"""

        l_block_number = self.w3.eth.get_block(l_block).get("number", BlockNumber(0))
        r_block_number = self.w3.eth.get_block(r_block).get("number", BlockNumber(0))

        by_no_id: Callable[[EventData], int] = lambda e: e["args"]["nodeOperatorId"]

        events = sorted(
            get_events_in_range(
                cast(ContractEvent, self.events.StuckSigningKeysCountChanged),
                l_block_number,
                r_block_number,
            ),
            key=by_no_id,
        )
        if not all(l_block_number <= e["blockNumber"] <= r_block_number for e in events):
            raise InconsistentEvents

        for no_id, group in groupby(events, key=by_no_id):
            if any(e["args"]["stuckKeysCount"] > 0 for e in group):
                yield NodeOperatorId(no_id)

    def is_paused(self, block: BlockIdentifier = "latest") -> bool:
        resp = self.functions.isPaused().call(block_identifier=block)
        logger.info(
            {
                "msg": "Call to isPaused()",
                "value": resp,
                "block_identifier": repr(block),
            }
        )
        return resp

    def node_operators_ids(self, block: BlockIdentifier = "latest") -> Iterable[NodeOperatorId]:
        for no_id in range(self.node_operators_count(block)):
            yield NodeOperatorId(no_id)

    def node_operators_count(self, block: BlockIdentifier = "latest") -> int:
        resp = self.functions.getNodeOperatorsCount().call(block_identifier=block)
        logger.info(
            {
                "msg": "Call to getNodeOperatorsCount()",
                "value": resp,
                "block_identifier": repr(block),
            }
        )
        return resp

    def node_operator_summary(self, no_id: NodeOperatorId, block: BlockIdentifier = "latest") -> NodeOperatorSummary:
        resp = self.functions.getNodeOperatorSummary(no_id).call(block_identifier=block)
        logger.info(
            {
                "msg": f"Call to getNodeOperatorSummary({no_id=})",
                "value": resp,
                "block_identifier": repr(block),
            }
        )
        return resp
