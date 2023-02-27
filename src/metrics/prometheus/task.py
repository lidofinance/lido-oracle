import logging
from functools import wraps
from time import perf_counter

from prometheus_client.context_managers import Timer

from src.metrics.prometheus.basic import TASKS_DURATION, TASKS_COUNT, Status

logger = logging.getLogger(__name__)


def task(name: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with TASKS_DURATION.labels(name=name).time() as t:
                t: Timer
                try:
                    logger.debug({"msg": f"Task '{name}' started"})
                    result = func(*args, **kwargs)
                    TASKS_COUNT.labels(name=name, status=Status.SUCCESS).inc()
                    return result
                except Exception as e:
                    TASKS_COUNT.labels(name=name, status=Status.FAILURE).inc()
                    raise e
                finally:
                    stop = perf_counter()
                    logger.debug({"msg": f"Task '{name}' finished", "duration (sec)": max(0, stop - t._start)})

        return wrapper

    return decorator
