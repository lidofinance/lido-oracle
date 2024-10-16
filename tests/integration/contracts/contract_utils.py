import logging
import re
from typing import Any, Callable

from src.providers.execution.base_interface import ContractInterface


HASH_REGREX = re.compile(r'^0x[0-9,A-F]{64}$', flags=re.IGNORECASE)
ADDRESS_REGREX = re.compile('^0x[0-9,A-F]{40}$', flags=re.IGNORECASE)


def check_contract(
    contract: ContractInterface,
    functions_spec: list[tuple[str, tuple | None, Callable[[Any], None]]],
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


def check_value_type(value, _type) -> None:
    assert isinstance(value, _type)
