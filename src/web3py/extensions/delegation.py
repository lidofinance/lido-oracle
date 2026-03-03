import logging
from typing import cast

from eth_typing import ChecksumAddress
from web3 import Web3
from web3.contract.contract import ContractFunction
from web3.module import Module

from src import variables
from src.providers.execution.contracts.delegation_contract import DelegationContract


logger = logging.getLogger(__name__)


class DelegationNotConfiguredError(Exception):
    """Raised when delegation contract has no delegatee assigned"""
    pass


class DelegateMismatchError(Exception):
    """Raised when delegation contract delegatee doesn't match oracle account"""
    pass


class DelegationModule(Module):
    w3: Web3
    delegation_contract: DelegationContract | None
    delegation_address: str | None

    def __init__(self, w3: Web3, delegation_address: str | None = None):
        super().__init__(w3)

        self.delegation_address = delegation_address
        self.delegation_contract = None

        if delegation_address:
            self.delegation_contract = cast(
                DelegationContract,
                self.w3.eth.contract(
                    address=cast(ChecksumAddress, delegation_address),
                    ContractFactoryClass=DelegationContract,
                    decode_tuples=True,
                ),
            )

            logger.info({
                'msg': 'DelegationModule initialized with contract',
                'delegation_address': delegation_address
            })

            self._validate_delegation_setup()
        else:
            logger.info({'msg': 'DelegationModule initialized without contract - delegation disabled'})

    def is_enabled(self) -> bool:
        return self.delegation_contract is not None

    def wrap_call_for_delegation(self, target_contract_call: ContractFunction) -> ContractFunction:
        """Convert normal contract call to delegated execution

        Args:
            target_contract_call: Original contract function call

        Returns:
            ContractFunction that calls delegation.execute() with encoded data
        """
        if not self.delegation_contract:
            raise RuntimeError("Delegation is not enabled - no contract address configured")

        target_address = str(target_contract_call.address)
        contract = self.w3.eth.contract(address=target_contract_call.address, abi=target_contract_call.contract_abi)
        encoded = contract.encode_abi(target_contract_call.fn_name, target_contract_call.args)
        calldata = bytes.fromhex(encoded[2:])

        logger.debug({
            'msg': 'Wrapping call for delegation',
            'target': target_address,
            'calldata_length': len(calldata)
        })

        return self.delegation_contract.execute(target_address, calldata)

    def _validate_delegation_setup(self) -> None:
        """Validate delegation contract is properly configured for oracle account"""

        if not self.delegation_contract:
            return

        current_delegatee = self.delegation_contract.get_delegatee()
        oracle_address = cast(ChecksumAddress, variables.ACCOUNT.address)

        if current_delegatee == '0x0000000000000000000000000000000000000000':
            raise DelegationNotConfiguredError(
                f"Delegation contract has no delegatee assigned. "
                f"Admin must call assignDelegate({oracle_address})"
            )

        if current_delegatee.lower() != oracle_address.lower():
            raise DelegateMismatchError(
                f"Delegation contract delegatee ({current_delegatee}) "
                f"does not match oracle account ({oracle_address}). "
                f"Admin must call assignDelegate({oracle_address})"
            )

        admin_address = self.delegation_contract.get_admin()

        logger.info({
            'msg': 'Delegation contract validation passed',
            'delegatee': current_delegatee,
            'oracle_account': oracle_address,
            'admin': admin_address,
            'delegation_contract': self.delegation_contract.address
        })
