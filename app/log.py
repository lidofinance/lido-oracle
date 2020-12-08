import sys
import logging


def init_log():
    """ initialize root logger """
    assert not hasattr(init_log, '_called'), 'init_log must be called only once!'
    init_log._called = True
    root_logger = logging.getLogger()
    _setup_logger(root_logger)


def _setup_logger(
        logger: logging.Logger,
        fmt: str = '%(levelname)8s %(asctime)s <daemon> %(message)s',
        datefmt: str = '%Y-%m-%d %H:%M:%S',
):
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(fmt, datefmt=datefmt)

    h_stdout = logging.StreamHandler(sys.stdout)
    h_stdout.setLevel(logging.DEBUG)
    h_stdout.addFilter(lambda record: record.levelno <= logging.INFO)
    h_stdout.setFormatter(formatter)
    logger.addHandler(h_stdout)

    h_stderr = logging.StreamHandler()
    h_stderr.setLevel(logging.WARNING)
    h_stderr.setFormatter(formatter)
    logger.addHandler(h_stderr)
