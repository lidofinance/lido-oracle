import logging

from hexbytes import HexBytes
from web3.types import BlockIdentifier

from ..base_interface import ContractInterface

logger = logging.getLogger(__name__)


class CSStrikesContract(ContractInterface):
    abi_path = "./assets/CSStrikes.json"

    def tree_root(self, block_identifier: BlockIdentifier = "latest") -> HexBytes:
        """Root of the latest published Merkle tree"""

        resp = self.functions.treeRoot().call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": "Call `treeRoot()`.",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return HexBytes(resp)

    def tree_cid(self, block_identifier: BlockIdentifier = "latest") -> str:
        """CID of the latest published Merkle tree"""

        resp = self.functions.treeCid().call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": "Call `treeCid()`.",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return resp
