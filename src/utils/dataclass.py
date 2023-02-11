import functools
from dataclasses import dataclass, is_dataclass, fields
from types import GenericAlias


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
    def decorator(func):
        @functools.wraps(func)
        def wrapper_decorator(*args, **kwargs):
            list_of_dicts = func(*args, **kwargs)
            return list(map(lambda x: _dataclass(**x), list_of_dicts))
        return wrapper_decorator

    return decorator
