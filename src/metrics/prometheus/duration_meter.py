import logging
from functools import wraps
from time import perf_counter
from types import FunctionType

from src.metrics.prometheus.basic import FUNCTIONS_DURATION, Status


logger = logging.getLogger(__name__)


def duration_meter():
    def decorator(func: FunctionType):
        @wraps(func)
        def wrapper(*args, **kwargs) -> FunctionType:
            full_name = f"{func.__module__}.{func.__name__}"
            with FUNCTIONS_DURATION.time() as t:
                try:
                    logger.debug({"msg": f"Function '{full_name}' started"})
                    result = func(*args, **kwargs)
                    t.labels(name=full_name, status=Status.SUCCESS)
                    return result
                except Exception as e:
                    t.labels(name=full_name, status=Status.FAILURE)
                    raise e
                finally:
                    stop = perf_counter()
                    logger.debug({
                        "msg": f"Task '{full_name}' finished", "duration (sec)": stop - t._start  # pylint: disable=protected-access
                    })

        return wrapper

    return decorator
