import functools
from weakref import WeakKeyDictionary

from web3.types import BlockParams, BlockIdentifier

from src.providers.execution.base_interface import ContractInterface

global_cache: WeakKeyDictionary = WeakKeyDictionary()


def global_lru_cache(*args, **kwargs):
    def caching_decorator(func):
        cached_func = functools.lru_cache(*args, **kwargs)(func)

        def wrapper(*args, **kwargs):
            # If lru_cache is on contract
            # Do not cache any requests with relative blocks
            # Like 'latest', 'earliest', 'pending', 'safe', 'finalized' or if default block provided
            if issubclass(args[0].__class__, ContractInterface):
                block = kwargs.get('block_identifier', None)

                # In case when args[-1] is not Class Instance
                if block is None and type(args[-1]) in BlockIdentifier.__args__:
                    block = args[-1]
                    kwargs['block_identifier'] = args[-1]
                    args = args[:-1]

                if block is None or block in BlockParams.__args__:
                    return func(*args, **kwargs)

            result = cached_func(*args, **kwargs)
            global_cache[func] = cached_func
            return result

        def cache_clear():
            cached_func.cache_clear()
            if func in global_cache:
                del global_cache[func]

        wrapper.cache_clear = cache_clear
        wrapper.cache_info = cached_func.cache_info
        return wrapper

    return caching_decorator


def clear_global_cache():
    for cached_func in global_cache.values():
        cached_func.cache_clear()
    global_cache.clear()
