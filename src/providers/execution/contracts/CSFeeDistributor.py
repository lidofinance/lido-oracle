import logging

from web3.contract.contract import Contract
from web3.types import BlockIdentifier

logger = logging.getLogger(__name__)


class CSFeeDistributor(Contract):
    abi_path = "./assets/CSFeeDistributor.json"

    def pending_to_distribute(self, block: BlockIdentifier = "latest") -> int:
        """Returns the amount of shares that are pending to be distributed"""

        resp = self.functions.pendingToDistribute().call(block_identifier=block)
        logger.debug(
            {
                "msg": "Call to pendingToDistribute()",
                "value": resp,
                "block_identifier": repr(block),
            }
        )
        return resp

    def tree_cid(self, block: BlockIdentifier = "latest") -> str:
        """CID of the latest published Merkle tree"""

        resp = self.functions.treeCid().call(block_identifier=block)
        logger.debug(
            {
                "msg": "Call to treeCid()",
                "value": resp,
                "block_identifier": repr(block),
            }
        )
        return resp
