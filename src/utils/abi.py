import re
from collections.abc import Callable
from typing import TypeVar


def camel_to_snake(name):
    name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()


T = TypeVar('T')


def named_tuple_to_dataclass(response, dataclass_factory: Callable[..., T] | type[T]) -> T:
    """
    Converts ABIDecodedNamedTuple to provided dataclass
    Example:
        Input: ABIDecodedNamedTuple(slotsPerEpoch=32, secondsPerSlot=12, genesisTime=1675263480)
        Output: ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=1675263480)
    """
    return dataclass_factory(**{camel_to_snake(key): value for key, value in response._asdict().items()})
