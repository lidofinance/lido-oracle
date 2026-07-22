import logging

from eth_typing import ChecksumAddress
from web3 import Web3
from web3.contract.contract import ContractFunction
from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface


logger = logging.getLogger(__name__)


class DelegationContract(ContractInterface):
    abi_path = './assets/DelegationContract.json'

    def execute(self, target: str, data: bytes) -> ContractFunction:
        """Build execute call for delegation: execute(address target, bytes data)

        Args:
            target: Address of the target contract to call
            data: The calldata to execute on target contract

        Returns:
            ContractFunction for execute() call
        """
        tx = self.functions.execute(target, data)

        logger.info(
            {
                'msg': 'Build delegation execute transaction',
                'target': target,
                'data_length': len(data),
                'to': self.address,
            }
        )
        return tx

    def get_owner(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        """Get delegate contract owner"""
        response = self.functions.owner().call(block_identifier=block_identifier)
        logger.info(
            {'msg': 'Call owner()', 'value': response, 'block_identifier': repr(block_identifier), 'to': self.address}
        )
        return Web3.to_checksum_address(response)

    def get_delegate(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        """Get the current delegate address"""
        response = self.functions.getDelegate().call(block_identifier=block_identifier)
        logger.info(
            {
                'msg': 'Call getDelegate()',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )
        return Web3.to_checksum_address(response)
