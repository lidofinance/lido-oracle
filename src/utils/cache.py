import functools
from weakref import WeakKeyDictionary

global_cache: WeakKeyDictionary = WeakKeyDictionary()


def global_lru_cache(*args, **kwargs):
    def caching_decorator(func):
        cached_func = functools.lru_cache(*args, **kwargs)(func)

        def wrapper(*args, **kwargs):
            result = cached_func(*args, **kwargs)
            global_cache[func] = cached_func
            return result

        def clear_cache():
            cached_func.cache_clear()
            if func in global_cache:
                del global_cache[func]

        wrapper.clear_cache = clear_cache
        wrapper.cache_info = cached_func.cache_info
        return wrapper

    return caching_decorator


def clear_global_cache():
    for cached_func in global_cache.values():
        cached_func.cache_clear()
    global_cache.clear()
