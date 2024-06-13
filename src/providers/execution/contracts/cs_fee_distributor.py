import logging

from hexbytes import HexBytes
from web3.types import BlockIdentifier

from ..base_interface import ContractInterface

logger = logging.getLogger(__name__)


class CSFeeDistributorContract(ContractInterface):
    abi_path = "./assets/CSFeeDistributor.json"

    def shares_to_distribute(self, block: BlockIdentifier = "latest") -> int:
        """Returns the amount of shares that are pending to be distributed"""

        resp = self.functions.pendingSharesToDistribute().call(block_identifier=block)
        logger.debug(
            {
                "msg": "Call to pendingSharesToDistribute()",
                "value": resp,
                "block_identifier": repr(block),
            }
        )
        return resp

    def tree_root(self, block: BlockIdentifier = "latest") -> HexBytes:
        """Root of the latest published Merkle tree"""

        resp = self.functions.treeRoot().call(block_identifier=block)
        logger.info(
            {
                "msg": "Call to treeRoot()",
                "value": resp,
                "block_identifier": repr(block),
            }
        )
        return HexBytes(resp)

    def tree_cid(self, block: BlockIdentifier = "latest") -> str:
        """CID of the latest published Merkle tree"""

        resp = self.functions.treeCid().call(block_identifier=block)
        logger.info(
            {
                "msg": "Call to treeCid()",
                "value": resp,
                "block_identifier": repr(block),
            }
        )
        return resp
