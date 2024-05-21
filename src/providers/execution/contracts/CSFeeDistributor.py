import logging

from web3.types import BlockIdentifier

from ..base_interface import ContractInterface

logger = logging.getLogger(__name__)


class CSFeeDistributor(ContractInterface):
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

    def tree_root(self, block: BlockIdentifier = "latest") -> str:
        """Root of the latest published Merkle tree"""

        resp = self.functions.treeRoot().call(block_identifier=block)
        logger.debug(
            {
                "msg": "Call to treeRoot()",
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
