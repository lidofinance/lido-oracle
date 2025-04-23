import itertools
from typing import Any, Callable, Tuple

from eth_abi.exceptions import DecodingError
from eth_typing import (
    ABI,
    ABIFunction,
)
from eth_typing import ChecksumAddress
from eth_utils.abi import (
    get_abi_output_types,
)
from web3 import Web3
from web3._utils.abi import (
    map_abi_data,
    named_tree,
    recursive_dict_to_namedtuple,
)
from web3._utils.contracts import prepare_transaction
from web3._utils.normalizers import BASE_RETURN_NORMALIZERS
from web3.contract import Contract as _Contract
from web3.contract.contract import ContractFunction as _ContractFunction
from web3.contract.contract import ContractFunctions as _ContractFunctions
from web3.contract.utils import ACCEPTABLE_EMPTY_STRINGS
from web3.exceptions import BadFunctionCallOutput
from web3.types import (
    BlockIdentifier,
    StateOverride,
    ABIElementIdentifier,
    TxParams,
)
from web3.utils import get_abi_element


def call_contract_function(  # pylint: disable=keyword-arg-before-vararg,too-many-positional-arguments
    w3: "Web3",
    address: ChecksumAddress,
    normalizers: Tuple[Callable[..., Any], ...],
    function_identifier: ABIElementIdentifier,
    transaction: TxParams,
    block_id: BlockIdentifier | None = None,
    contract_abi: ABI | None = None,
    fn_abi: ABIFunction | None = None,
    state_override: StateOverride | None = None,
    ccip_read_enabled: bool | None = None,
    decode_tuples: bool | None = False,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """
    Helper function for interacting with a contract function using the
    `eth_call` API.
    """
    call_transaction = prepare_transaction(
        address,
        w3,
        abi_element_identifier=function_identifier,
        contract_abi=contract_abi,
        abi_callable=fn_abi,
        transaction=transaction,
        fn_args=args,
        fn_kwargs=kwargs,
    )

    return_data = w3.eth.call(
        call_transaction,
        block_identifier=block_id,
        state_override=state_override,
        ccip_read_enabled=ccip_read_enabled,
    )

    if fn_abi is None:
        fn_abi = get_abi_element(
            contract_abi,
            function_identifier,
            *args,
            abi_codec=w3.codec,
            **kwargs,
        )

    output_types = get_abi_output_types(fn_abi)

    try:
        output_data = w3.codec.decode(output_types, return_data)
    except DecodingError as e:
        # Provide a more helpful error message than the one provided by
        # eth-abi-utils
        is_missing_code_error = (
            return_data in ACCEPTABLE_EMPTY_STRINGS
            and w3.eth.get_code(address) in ACCEPTABLE_EMPTY_STRINGS
        )
        if is_missing_code_error:
            msg = (
                "Could not transact with/call contract function, is contract "
                "deployed correctly and chain synced?"
            )
        else:
            msg = (
                f"Could not decode contract function call to {function_identifier} "
                f"with return data: {str(return_data)}, output_types: {output_types}"
            )
        raise BadFunctionCallOutput(msg) from e

    _normalizers = itertools.chain(
        BASE_RETURN_NORMALIZERS,
        normalizers,
    )
    normalized_data = map_abi_data(_normalizers, output_types, output_data)

    # Fast tweak. Don't need to decode args
    if decode_tuples and fn_abi["outputs"]:
        decoded = named_tree(fn_abi["outputs"], normalized_data)
        normalized_data = recursive_dict_to_namedtuple(decoded)

    if len(normalized_data) == 1:  # pylint: disable=no-else-return
        return normalized_data[0]
    else:
        return normalized_data


class ContractFunction(_ContractFunction):
    def call(
        self,
        transaction: TxParams | None = None,
        block_identifier: BlockIdentifier = "latest",
        state_override: StateOverride | None = None,
        ccip_read_enabled: bool | None = None,
    ) -> Any:
        call_transaction = self._get_call_txparams(transaction)

        return call_contract_function(
            self.w3,
            self.address,
            self._return_data_normalizers,
            self.abi_element_identifier,
            call_transaction,
            block_identifier,
            self.contract_abi,
            self.abi,
            state_override,
            ccip_read_enabled,
            self.decode_tuples,
            *self.args or (),
            **self.kwargs or {},
        )


class ContractFunctions(_ContractFunctions):
    def __init__(
        self,
        abi: ABI,
        w3: Web3,
        address: ChecksumAddress | None = None,
        decode_tuples: bool | None = False,
    ) -> None:
        # skip init for class _ContractFunctions
        super(_ContractFunctions, self).__init__(abi, w3, ContractFunction, address, decode_tuples)


class Contract(_Contract):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.functions = ContractFunctions(self.abi, self.w3, self.address, decode_tuples=self.decode_tuples)


def tweak_w3_contracts(w3: Web3):
    """
    Normal call to contract's method with blockhash would parse blockhash into block_number.
    Remove parse_block_identifier(self.w3, block_identifier) from ContractFunction and setup new ContractFactory
    to remove redundant eth_getBlockByHash call.

    Here are two tweaks:
    1. https://github.com/ethereum/web3.py/issues/2816
    2. https://github.com/ethereum/web3.py/issues/2865
    """
    w3.eth._default_contract_factory = Contract  # pylint: disable=protected-access
