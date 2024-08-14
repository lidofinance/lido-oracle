import logging

from eth_typing import ChecksumAddress
from web3 import Web3
from web3.types import BlockIdentifier

from ..base_interface import ContractInterface

logger = logging.getLogger(__name__)


class CSAccountingContract(ContractInterface):
    abi_path = "./assets/CSAccounting.json"

    def fee_distributor(self, block_identifier: BlockIdentifier = "latest") -> ChecksumAddress:
        """Returns the address of the CSFeeDistributor contract"""

        resp = self.functions.feeDistributor().call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": "Call `feeDistributor()`.",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return Web3.to_checksum_address(resp)
