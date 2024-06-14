from typing import Iterable, TypeVar, cast

T = TypeVar("T", bound=int)


def sequence(start: T, stop: T) -> Iterable[T]:
    """Returns inclusive range object [start;stop]"""
    if start > stop:
        raise ValueError(f"{start=} > {stop=}")
    return cast(Iterable, range(start, stop + 1))
