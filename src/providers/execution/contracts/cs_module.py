import logging
from typing import Iterable, NamedTuple

from web3.types import BlockIdentifier


from src.utils.cache import global_lru_cache as lru_cache
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
