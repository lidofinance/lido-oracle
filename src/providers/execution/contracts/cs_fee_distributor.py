import logging

from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from web3 import Web3
from web3.types import BlockIdentifier, Wei

from ..base_interface import ContractInterface

logger = logging.getLogger(__name__)


class CSFeeDistributorContract(ContractInterface):
    abi_path = "./assets/CSFeeDistributor.json"

    def oracle(self, block_identifier: BlockIdentifier = "latest") -> ChecksumAddress:
        """Returns the address of the CSFeeOracle contract"""

        resp = self.functions.ORACLE().call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": "Call `ORACLE()`.",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return Web3.to_checksum_address(resp)

    def shares_to_distribute(self, block_identifier: BlockIdentifier = "latest") -> Wei:
        """Returns the amount of shares that are pending to be distributed"""

        resp = self.functions.pendingSharesToDistribute().call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": "Call `pendingSharesToDistribute()`.",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return resp

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
