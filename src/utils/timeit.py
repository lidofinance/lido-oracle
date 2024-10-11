import time
from functools import wraps
from types import SimpleNamespace
from typing import Callable


type Arguments = SimpleNamespace
type Duration = float


def timeit(log_fn: Callable[[Arguments, Duration], None]):
    def decorator[T](func: Callable[..., T]):
        @wraps(func)
        def wrapped(*args, **kwargs) -> T:
            start_time = time.time()
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            arguments = SimpleNamespace(**dict(zip(func.__code__.co_varnames, args)), **kwargs)
            log_fn(arguments, execution_time)
            return result

        return wrapped

    return decorator
