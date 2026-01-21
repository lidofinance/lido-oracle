import functools
from inspect import signature
from weakref import WeakKeyDictionary

from src.providers.execution.base_interface import ContractInterface


global_cache: WeakKeyDictionary = WeakKeyDictionary()


def _is_contract_interface_method(func, instance):
    """
    Check if the function is a ContractInterface method.
    
    In Python 3.14+, bound methods may not pass self through args,
    so we need to check both the instance and the function's qualname.
    """
    if instance and issubclass(instance.__class__, ContractInterface):
        return True
    
    # Fallback: Check if function qualname suggests it's from ContractInterface
    qualname = getattr(func, '__qualname__', '')
    if '.' in qualname:
        try:
            # Check if any parent class of the function's owner is ContractInterface
            module_name = func.__module__
            if module_name and 'providers.execution.contracts' in module_name:
                return True
        except (AttributeError, ImportError):
            pass
    
    return False


def global_lru_cache(*args, **kwargs):
    def caching_decorator(func):
        cached_func = functools.lru_cache(*args, **kwargs)(func)

        def wrapper(*args, **kwargs):
            # if lru_cache used for caching ContractInterface method
            # Do not cache any requests with relative blocks
            # Like 'latest', 'earliest', 'pending', 'safe', 'finalized' or if default ('latest') arg provided
            args_list = signature(func).parameters

            instance = args[0] if args else None
            
            if _is_contract_interface_method(func, instance) and args_list.get('block_identifier'):
                block = kwargs.get('block_identifier', None)
                if block is None:
                    if len(args) == len(args_list):
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
