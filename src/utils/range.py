from typing import cast, Iterable, TypeVar


T = TypeVar("T", bound=int)


def sequence(start: T, stop: T) -> Iterable[T]:
    """Returns inclusive range object [start;stop]"""
    assert stop > 0
    return cast(Iterable, range(start, stop + 1))
