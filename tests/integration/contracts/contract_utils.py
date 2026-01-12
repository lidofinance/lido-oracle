import logging
import re
from dataclasses import is_dataclass, fields
from types import UnionType
from typing import Any, Callable, Type, get_type_hints, get_origin

from eth_typing import Address, ChecksumAddress

from src.providers.execution.base_interface import ContractInterface

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


def check_is_instance_of(type_: Type) -> Callable[[FuncArgs], None]:
    if type_ is Address or type_ is ChecksumAddress:
        return lambda resp: check_is_address(resp) and check_value_type(resp, type_)

    if is_dataclass(type_):
        return lambda resp: check_dataclass_types(resp, type_)

    return lambda resp: check_value_type(resp, type_)


def check_value_type(value, type_) -> None:
    assert isinstance(value, type_), f"Got invalid type={type(value)}, expected={repr(type_)}"


def check_dataclass_types(instance, dataclass_type_) -> None:
    hints = get_type_hints(dataclass_type_)  # declared types
    for f in fields(instance):
        value = getattr(instance, f.name)
        expected_type = hints[f.name]

        # If an annotation was created using NewType, we have to find the base type.
        while hasattr(expected_type, "__supertype__"):
            expected_type = expected_type.__supertype__

        if origin := get_origin(expected_type):
            if origin is not UnionType:
                expected_type = origin
        elif hasattr(expected_type, "__base__"):
            expected_type = expected_type.__base__

        assert isinstance(value, expected_type), f"Got invalid type={type(value)}, expected={repr(origin)}"


def check_is_address(resp: FuncResp) -> None:
    assert isinstance(resp, str), "address should be returned as a string"
    check_value_re(ADDRESS_REGREX, resp)


def check_value_re(regrex, value) -> None:
    assert regrex.findall(value), f"{value=} doesn't match {regrex=}"
