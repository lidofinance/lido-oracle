import functools
from weakref import WeakKeyDictionary

from src.providers.execution.base_interface import ContractInterface

global_cache: WeakKeyDictionary = WeakKeyDictionary()


def global_lru_cache(*args, **kwargs):
    def caching_decorator(func):
        cached_func = functools.lru_cache(*args, **kwargs)(func)

        def wrapper(*args, **kwargs):
            # if lru_cache used for caching ContractInterface method
            # Do not cache any requests with relative blocks
            # Like 'latest', 'earliest', 'pending', 'safe', 'finalized' or if default ('latest') arg provided
            var_names = func.__code__.co_varnames

            if issubclass(args[0].__class__, ContractInterface) and var_names[-1] == 'block_identifier':
                block = kwargs.get('block_identifier', None)
                if block is None:
                    if len(args) == len(var_names):
                        # block_identifier provided via kwargs and args
                        block = args[-1]
                        # Move to kwarg
                        kwargs['block_identifier'] = block
                        args = args[:-1]
                    else:
                        # block_identifier not provided
                        return func(*args, **kwargs)

                if block in ['latest', 'earliest', 'pending', 'safe', 'finalized']:
                    # block_identifier one of related markers
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
