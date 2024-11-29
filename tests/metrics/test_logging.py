import json
import logging
from unittest.mock import Mock
import pytest

from src.metrics.logging import JsonFormatter


@pytest.fixture
def log_record():
    """Fixture to create a basic log record for testing."""
    record = Mock(spec=logging.LogRecord)
    record.created = 1638280000.0
    record.name = "test_logger"
    record.levelname = "INFO"
    record.funcName = "test_function"
    record.lineno = 10
    record.module = "test_module"
    record.pathname = "/path/to/test_module.py"
    return record


@pytest.mark.unit
def test_format_regular_message(log_record):
    """Test formatting a regular log message."""
    log_record.msg = "Test message"
    log_record.getMessage = lambda: "Test message"
    formatter = JsonFormatter()

    formatted_output = formatter.format(log_record)
    expected_output = json.dumps(
        {
            'timestamp': int(log_record.created),
            'name': log_record.name,
            'levelname': log_record.levelname,
            'funcName': log_record.funcName,
            'lineno': log_record.lineno,
            'module': log_record.module,
            'pathname': log_record.pathname,
            'msg': log_record.getMessage(),
        }
    )

    assert formatted_output == expected_output


@pytest.mark.unit
def test_format_dict_message(log_record):
    """Test formatting a log message that is a dictionary."""
    log_record.msg = {'key': 'value', 'another_key': 123}
    log_record.getMessage = lambda: "Should not be used"
    formatter = JsonFormatter()

    formatted_output = formatter.format(log_record)
    expected_output = json.dumps(
        {
            'timestamp': int(log_record.created),
            'name': log_record.name,
            'levelname': log_record.levelname,
            'funcName': log_record.funcName,
            'lineno': log_record.lineno,
            'module': log_record.module,
            'pathname': log_record.pathname,
            'key': 'value',
            'another_key': 123,
        }
    )

    assert formatted_output == expected_output


@pytest.mark.unit
def test_format_message_with_value_field(log_record):
    """Test formatting a log message where the message contains a 'value' field."""
    log_record.msg = {'msg': 'Test message', 'value': 456}
    log_record.getMessage = lambda: "Should not be used"
    formatter = JsonFormatter()

    formatted_output = formatter.format(log_record)
    expected_output = json.dumps(
        {
            'timestamp': int(log_record.created),
            'name': log_record.name,
            'levelname': log_record.levelname,
            'funcName': log_record.funcName,
            'lineno': log_record.lineno,
            'module': log_record.module,
            'pathname': log_record.pathname,
            'msg': 'Test message',
            'value': '456',  # 'value' field should be converted to string
        }
    )

    assert formatted_output == expected_output


@pytest.mark.unit
def test_format_empty_message(log_record):
    """Test formatting when the message is empty."""
    log_record.msg = ""
    log_record.getMessage = lambda: ""
    formatter = JsonFormatter()

    formatted_output = formatter.format(log_record)
    expected_output = json.dumps(
        {
            'timestamp': int(log_record.created),
            'name': log_record.name,
            'levelname': log_record.levelname,
            'funcName': log_record.funcName,
            'lineno': log_record.lineno,
            'module': log_record.module,
            'pathname': log_record.pathname,
            'msg': '',
        }
    )

    assert formatted_output == expected_output
