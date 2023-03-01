import functools
from dataclasses import dataclass, is_dataclass, fields
from types import GenericAlias
from typing import Callable

from src.utils.abi import named_tuple_to_dataclass


class DecodeToDataclassException(Exception):
    pass


@dataclass
class Nested:
    """
    Base class for dataclasses that converts all inner dicts into dataclasses
    Also works with lists of dataclasses
    """
    def __post_init__(self):
        for field in fields(self):
            if isinstance(field.type, GenericAlias):
                field_type = field.type.__args__[0]
                if is_dataclass(field_type):
                    setattr(self, field.name,
                            field.type.__origin__(map(
                                lambda x: field_type(**x) if not is_dataclass(x) else x,
                                getattr(self, field.name))))
            elif is_dataclass(field.type) and not is_dataclass(getattr(self, field.name)):
                setattr(self, field.name, field.type(**getattr(self, field.name)))


def list_of_dataclasses(_dataclass):
    """Decorator to transform list of dicts from func response to list of dataclasses"""
    def decorator(func) -> Callable:
        @functools.wraps(func)
        def wrapper_decorator(*args, **kwargs):
            list_of_elements = func(*args, **kwargs)

            if isinstance(list_of_elements[0], dict):
                return list(map(lambda x: _dataclass(**x), list_of_elements))

            if isinstance(list_of_elements[0], tuple):
                return list(map(lambda x: named_tuple_to_dataclass(x, _dataclass), list_of_elements))

            raise DecodeToDataclassException(f'Type {type(list_of_elements[0])} is not supported.')
        return wrapper_decorator

    return decorator
