import logging

from app.log import _setup_logger


def test_debug_stdout(capsys):
    logger = logging.getLogger('test_debug_stdout')
    logger.setLevel(logging.DEBUG)
    _setup_logger(logger, '%(levelname)s %(message)s', stdout_level='DEBUG')
    logger.debug('some debug log')
    captured = capsys.readouterr()
    assert captured.out.strip() == "DEBUG some debug log"
    assert captured.err == ""


def test_info_stdout(capsys):
    logger = logging.getLogger('test_info_stdout')
    logger.setLevel(logging.INFO)
    _setup_logger(logger, '%(levelname)s %(message)s')
    logger.info('some info log')
    captured = capsys.readouterr()
    assert captured.out.strip() == "INFO some info log"
    assert captured.err == ""


def test_warning_stdout(capsys):
    logger = logging.getLogger('test_warning_stdout')
    _setup_logger(logger, '%(levelname)s %(message)s')
    logger.warning('some warning log')
    captured = capsys.readouterr()
    assert captured.out.strip() == "WARNING some warning log"
    assert captured.err == ""


def test_error_stdout(capsys):
    logger = logging.getLogger('test_error_stdout')
    _setup_logger(logger, '%(levelname)s %(message)s')
    logger.error('some error log')
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "ERROR some error log"
