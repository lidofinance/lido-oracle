import json
from functools import lru_cache
import logging
from typing import cast

from eth_typing.evm import Address, ChecksumAddress
from web3.contract.contract import Contract
from web3.types import BlockIdentifier

from src.typings import SlotNumber

logger = logging.getLogger(__name__)


class CSFeeOracle(Contract):
    abi_path = "./assets/CSFeeOracle.json"

    # TODO: Inherit from the base class.
    def __init__(self, address: ChecksumAddress | None = None) -> None:
        with open(self.abi_path, encoding="utf-8") as f:
            self.abi = json.load(f)
        super().__init__(address)

    def fee_distributor(self, block: BlockIdentifier = "latest") -> Address:
        """Returns the address of the CSFeeDistributor"""

        resp = self.functions.feeDistributor().call(block_identifier=block)
        logger.debug(
            {
                "msg": "Call to feeDistributor()",
                "value": resp,
                "block_identifier": repr(block),
            }
        )
        return cast(Address, resp)

    # TODO: Inherit the method from the BaseOracle class.
    @lru_cache(maxsize=1)
    def get_last_processing_ref_slot(self, block: BlockIdentifier = "latest") -> SlotNumber:
        resp = self.functions.getLastProcessingRefSlot().call(block_identifier=block)
        logger.debug(
            {
                "msg": "Call to getLastProcessingRefSlot()",
                "value": resp,
                "block_identifier": repr(block),
            }
        )
        return SlotNumber(resp)