import signal
import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from types import FrameType

from src.metrics.logging import logging


logger = logging.getLogger(__name__)


@contextmanager
def graceful_shutdown_signal_handlers() -> Iterator[None]:
    """
    Temporarily convert `SIGINT` and `SIGTERM` to `SystemExit(0)`.

    Use this around a top-level module run loop so regular `finally` cleanup
    still runs on process shutdown. The previous handlers are restored when the
    context exits.
    """
    if threading.current_thread() is not threading.main_thread():
        logger.info({'msg': 'Cannot manage signal handlers outside main thread'})
        yield
        return

    def shutdown_signal_handler(signum: int, _frame: FrameType | None) -> None:
        logger.info(
            {'msg': 'Received shutdown signal. Requesting graceful exit.', 'signal': signal.Signals(signum).name}
        )
        raise SystemExit(0)

    with ExitStack() as stack:
        for stop_signal in (signal.SIGINT, signal.SIGTERM):
            previous_handler = signal.signal(stop_signal, shutdown_signal_handler)
            stack.callback(signal.signal, stop_signal, previous_handler)
        yield
