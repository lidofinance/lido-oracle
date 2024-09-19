import logging

from eth_typing import BlockIdentifier

from ..base_interface import ContractInterface

logger = logging.getLogger(__name__)


class DepositContract(ContractInterface):
    abi_path = "./assets/DepositContract.json"

    def get_deposit_count(self, block_identifier: BlockIdentifier) -> int:
        resp = self.functions.get_deposit_count().call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": "Call `get_deposit_count()`.",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return int.from_bytes(resp, "little")
