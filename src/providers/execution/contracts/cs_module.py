import logging

from eth_typing import ChecksumAddress
from web3 import Web3
from web3.types import BlockIdentifier

from src.constants import UINT64_MAX

from ..base_interface import ContractInterface

logger = logging.getLogger(__name__)


class CSModuleContract(ContractInterface):
    abi_path = "./assets/CSModule.json"

    MAX_OPERATORS_COUNT = UINT64_MAX

    def accounting(self, block_identifier: BlockIdentifier = "latest") -> ChecksumAddress:
        """Returns the address of the CSAccounting contract"""

        resp = self.functions.accounting().call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": "Call `accounting()`.",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return Web3.to_checksum_address(resp)

    def parameters_registry(self, block_identifier: BlockIdentifier = "latest") -> ChecksumAddress:
        """Returns the address of the CSParametersRegistry contract"""

        resp = self.functions.PARAMETERS_REGISTRY().call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": "Call `PARAMETERS_REGISTRY()`.",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return Web3.to_checksum_address(resp)

    def is_paused(self, block: BlockIdentifier = "latest") -> bool:
        resp = self.functions.isPaused().call(block_identifier=block)
        logger.info(
            {
                "msg": "Call `isPaused()`.",
                "value": resp,
                "block_identifier": repr(block),
            }
        )
        return resp
