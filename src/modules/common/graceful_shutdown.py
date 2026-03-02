import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import FrameType

from src.metrics.logging import logging


logger = logging.getLogger(__name__)


type SignalHandler = Callable[[int, FrameType | None], object] | int | None


def _shutdown_signal_handler(signum: int, _frame: FrameType | None) -> None:
    try:
        signal_name = signal.Signals(signum).name
    except ValueError:
        signal_name = str(signum)

    logger.info({'msg': 'Received shutdown signal. Requesting graceful exit.', 'signal': signal_name})
    raise SystemExit(0)


@contextmanager
def graceful_shutdown_signal_handlers() -> Iterator[None]:
    previous_handlers: dict[signal.Signals, SignalHandler] = {}

    for stop_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            previous_handlers[stop_signal] = signal.getsignal(stop_signal)
            signal.signal(stop_signal, _shutdown_signal_handler)
        except ValueError:
            logger.info({'msg': 'Cannot register signal handler outside main thread', 'signal': stop_signal})

    try:
        yield
    finally:
        for stop_signal, previous_handler in previous_handlers.items():
            try:
                signal.signal(stop_signal, previous_handler)
            except ValueError:
                logger.info({'msg': 'Cannot restore signal handler outside main thread', 'signal': stop_signal})
