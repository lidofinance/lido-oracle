import logging
import re
from typing import Any, Callable, Type

from eth_typing import Address, ChecksumAddress

from src.providers.execution.base_interface import ContractInterface
from src.utils.types import hex_str_to_bytes

HASH_REGREX = re.compile(r'^0x[0-9,A-F]{64}$', flags=re.IGNORECASE)
ADDRESS_REGREX = re.compile('^0x[0-9,A-F]{40}$', flags=re.IGNORECASE)

type FuncName = str
type FuncArgs = tuple
type FuncResp = Any


def check_contract(
    contract: ContractInterface,
    functions_spec: list[tuple[FuncName, FuncArgs | None, Callable[[FuncResp], None]]],
    caplog,
):
    caplog.set_level(logging.DEBUG)

    for function in functions_spec:
        # get method
        method = contract.__getattribute__(function[0])  # pylint: disable=unnecessary-dunder-call
        # call method with args
        response = method(*function[1]) if function[1] is not None else method()
        # check response
        function[2](response)

    log_with_call = list(filter(lambda log: 'Call ' in log or 'Build ' in log, caplog.messages))

    assert len(functions_spec) == len(log_with_call)


def check_value_re(regrex, value) -> None:
    assert regrex.findall(value)


def check_is_instance_of(type_: Type) -> Callable[[FuncArgs], None]:
    if type_ is Address or type_ is ChecksumAddress:
        return check_is_address
    return lambda resp: check_value_type(resp, type_)


def check_value_type(value, type_) -> None:
    assert isinstance(value, type_), f"Got invalid type={type(value)}, expected={repr(type_)}"


def check_is_address(resp: FuncResp) -> None:
    assert isinstance(resp, str), "address should be returned as a string"
    assert len(hex_str_to_bytes(resp)) == 20, "Got invalid address length"
