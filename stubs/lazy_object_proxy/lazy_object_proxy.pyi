from typing import Generic, Type, TypeVar


T = TypeVar("T")


class Proxy(Generic[T]):
    def __init__(self, factory: Type[T]) -> None: ...
