import json
import logging

from eth_typing.evm import ChecksumAddress
from web3.contract.contract import Contract
from web3.types import BlockIdentifier

logger = logging.getLogger(__name__)


class CSFeeDistributor(Contract):
    abi_path = "./assets/CSFeeDistributor.json"

    # TODO: Inherit from the base class.
    def __init__(self, address: ChecksumAddress | None = None) -> None:
        with open(self.abi_path, encoding="utf-8") as f:
            self.abi = json.load(f)
        super().__init__(address)

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
