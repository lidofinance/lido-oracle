import sys
import logging


def init_log(stdout_level: str = 'INFO'):
    """initialize root logger"""
    if hasattr(init_log, '_called'):
        logging.warning('init_log must be called only once!')
        return
    init_log._called = True
    root_logger = logging.getLogger()
    _setup_logger(root_logger, stdout_level=stdout_level)


def _setup_logger(
    logger: logging.Logger,
    fmt: str = '%(levelname)8s %(asctime)s <daemon> %(message)s',
    datefmt: str = '%Y-%m-%d %H:%M:%S',
    stdout_level: str = 'INFO',
):
    # Remove default handler
    if logger.handlers:
        logger.handlers = []

    formatter = logging.Formatter(fmt, datefmt=datefmt)

    h_stdout = logging.StreamHandler(sys.stdout)
    h_stdout.setLevel(stdout_level)
    h_stdout.addFilter(lambda record: record.levelno <= logging.WARNING)
    h_stdout.setFormatter(formatter)
    logger.addHandler(h_stdout)

    h_stderr = logging.StreamHandler(sys.stderr)
    h_stderr.setLevel(logging.ERROR)
    h_stderr.setFormatter(formatter)
    logger.addHandler(h_stderr)

    logger.setLevel(min(h_stdout.level, h_stderr.level))
