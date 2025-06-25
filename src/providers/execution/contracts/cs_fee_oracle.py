import logging

from eth_typing import ChecksumAddress
from web3 import Web3
from web3.types import BlockIdentifier

from src.providers.execution.contracts.base_oracle import BaseOracleContract

logger = logging.getLogger(__name__)


class CSFeeOracleContract(BaseOracleContract):
    abi_path = "./assets/CSFeeOracle.json"

    def is_paused(self, block_identifier: BlockIdentifier = "latest") -> bool:
        """Returns whether the contract is paused"""

        resp = self.functions.isPaused().call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": "Call `isPaused()`.",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return resp

    def strikes(self, block_identifier: BlockIdentifier = "latest") -> ChecksumAddress:
        """Return the address of the CSStrikes contract"""

        resp = self.functions.STRIKES().call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": "Call `STRIKES()`.",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return Web3.to_checksum_address(resp)
