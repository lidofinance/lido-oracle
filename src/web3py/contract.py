from typing import Optional, Any

from eth_typing import ChecksumAddress
from web3 import Web3
from web3.contract import (
    Contract as _Contract,
    ContractFunctions as _ContractFunctions,
    ContractFunction as _ContractFunction,
    call_contract_function,
)
from web3.types import ABI, TxParams, BlockIdentifier, CallOverride


"""
Remove parse_block_identifier(self.w3, block_identifier) from ContractFunction.
There is no need to transform block_hash into block_number.
"""


class ContractFunction(_ContractFunction):
    def call(
        self,
        transaction: Optional[TxParams] = None,
        block_identifier: BlockIdentifier = "latest",
        state_override: Optional[CallOverride] = None,
        ccip_read_enabled: Optional[bool] = None,
    ) -> Any:
        call_transaction = self._get_call_txparams(transaction)

        return call_contract_function(
            self.w3,
            self.address,
            self._return_data_normalizers,
            self.function_identifier,
            call_transaction,
            block_identifier,
            self.contract_abi,
            self.abi,
            state_override,
            ccip_read_enabled,
            *self.args,
            **self.kwargs,
        )


class ContractFunctions(_ContractFunctions):
    def __init__(self, abi: ABI, w3: Web3, address: Optional[ChecksumAddress] = None) -> None:
        # skip init for class _ContractFunctions
        super(_ContractFunctions, self).__init__(abi, w3, ContractFunction, address)


class Contract(_Contract):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.functions = ContractFunctions(self.abi, self.w3, self.address)


def tweak_w3_contracts(w3: Web3):
    w3.eth.defaultContractFactory = Contract
