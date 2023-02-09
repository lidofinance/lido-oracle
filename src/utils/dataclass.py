import functools
from dataclasses import dataclass, is_dataclass


def list_of_dataclasses(_dataclass):
    """Decorator to transform list of dicts from func response to list of dataclasses"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper_decorator(*args, **kwargs):
            list_of_dicts = func(*args, **kwargs)
            return list(map(lambda x: _dataclass(**x), list_of_dicts))
        return wrapper_decorator

    return decorator


def nested_dataclass(*args, **kwargs):
    """Decorator for dataclass that converts all inner dicts into dataclasses"""
    def wrapper(cls):
        cls = dataclass(cls, **kwargs)
        original_init = cls.__init__

        def __init__(self, *args, **kwargs):
            for name, value in kwargs.items():
                field_type = cls.__annotations__.get(name, None)
                if isinstance(value, list):
                    if field_type.__origin__ == list or field_type.__origin__ == list:
                        sub_type = field_type.__args__[0]
                        if is_dataclass(sub_type):
                            items = []
                            for child in value:
                                if isinstance(child, dict):
                                    items.append(sub_type(**child))
                            kwargs[name] = items
                if is_dataclass(field_type) and isinstance(value, dict):
                    new_obj = field_type(**value)
                    kwargs[name] = new_obj
            original_init(self, *args, **kwargs)

        cls.__init__ = __init__
        return cls

    return wrapper(args[0]) if args else wrapper
