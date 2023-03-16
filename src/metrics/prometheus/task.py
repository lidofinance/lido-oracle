import logging
from functools import wraps
from time import perf_counter
from typing import Callable

from src.metrics.prometheus.basic import TASKS_DURATION, Status

logger = logging.getLogger(__name__)


def task(name: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs) -> Callable:
            with TASKS_DURATION.time() as t:
                try:
                    logger.debug({"msg": f"Task '{name}' started"})
                    result = func(*args, **kwargs)
                    t.labels(name=name, status=Status.SUCCESS)
                    return result
                except Exception as e:
                    t.labels(name=name, status=Status.FAILURE)
                    raise e
                finally:
                    stop = perf_counter()
                    logger.debug({
                        "msg": f"Task '{name}' finished", "duration (sec)": max(0, stop - t._start)  # pylint: disable=protected-access
                    })

        return wrapper

    return decorator
