import logging
from typing import cast

from eth_typing.evm import Address
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
                "msg": "Call isPaused().",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return resp

    def fee_distributor(self, block_identifier: BlockIdentifier = "latest") -> Address:
        """Returns the address of the CSFeeDistributor"""

        resp = self.functions.feeDistributor().call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": "Call to feeDistributor()",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return cast(Address, resp)

    def perf_leeway_bp(self, block_identifier: BlockIdentifier = "latest") -> int:
        """Performance threshold leeway used to determine underperforming validators"""

        resp = self.functions.avgPerfLeewayBP().call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": "Call to avgPerfLeewayBP()",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return resp