import logging
from typing import cast

from eth_abi.abi import encode
from eth_typing import ChecksumAddress
from web3.contract.contract import ContractFunction
from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface


logger = logging.getLogger(__name__)


class DelegationContract(ContractInterface):
    abi_path = './assets/DelegationContract.json'

    def execute(self, target_address: str, calldata: bytes) -> ContractFunction:
        """Build execute call for delegation

        Args:
            target_address: Address of the target contract to call
            calldata: The calldata to execute on target contract

        Returns:
            ContractFunction for execute() call with encoded data
        """
        # Encode as (address, bytes) for the execute() function
        encoded_data = encode(['address', 'bytes'], [target_address, calldata])

        tx = self.functions.execute(encoded_data)
        logger.info({
            'msg': 'Build delegation execute transaction',
            'target': target_address,
            'calldata_length': len(calldata),
            'to': self.address
        })
        return tx

    def get_admin(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        """Get current admin address"""
        response = self.functions.admin().call(block_identifier=block_identifier)
        logger.debug({
            'msg': 'Call admin()',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address
        })
        return cast(ChecksumAddress, response)

    def get_delegatee(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        """Get current delegatee address"""
        response = self.functions.delegatee().call(block_identifier=block_identifier)
        logger.debug({
            'msg': 'Call delegatee()',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address
        })
        return cast(ChecksumAddress, response)

