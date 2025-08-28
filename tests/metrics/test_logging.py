import dataclasses
import json
import logging
from typing import Iterator
from unittest.mock import Mock

import pytest

from src.metrics.logging import JsonFormatter, convert_bytes_to_hex


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


@dataclasses.dataclass
class TestDataclass:
    field1: bytes
    field2: int


def byte_generator():
    yield b'\xde\xad'
    yield b'\xbe\xef'
    yield b'\xca\xfe'


@pytest.mark.unit
@pytest.mark.parametrize(
    "input_data, expected_output",
    [
        (b'\xde\xad\xbe\xef', "0xdeadbeef"),
        ({"key": b'\xca\xfe\xba\xbe'}, {"key": "0xcafebabe"}),
        ([b'\x00\xff'], ["0x00ff"]),
        ((b'\x12\x34', b'\xab\xcd'), ("0x1234", "0xabcd")),
        ({"nested": {"key": b'\x99\x88'}}, {"nested": {"key": "0x9988"}}),
        ([{"data": b'\xaa\xbb'}], [{"data": "0xaabb"}]),
        (TestDataclass(field1=b'\x11\x22', field2=42), {"field1": "0x1122", "field2": 42}),
        ("string", "string"),
        (12345, 12345),
        (None, None),
        ({b'\xde\xad', b'\xbe\xef'}, {"0xdead", "0xbeef"}),
    ],
)
def test_convert_bytes_to_hex(input_data, expected_output):
    assert convert_bytes_to_hex(input_data) == expected_output


@pytest.mark.unit
def test_convert_bytes_to_hex_generator():
    gen = byte_generator()
    converted_gen = convert_bytes_to_hex(gen)
    assert isinstance(converted_gen, Iterator)
    assert list(converted_gen) == ["0xdead", "0xbeef", "0xcafe"]
