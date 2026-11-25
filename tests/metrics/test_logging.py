import dataclasses
import json
import logging
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from logmask import JsonFormatter, SafeStreamHandler, SecretsMasker

from src import variables
from src.metrics.logging import ValueAsStringFilter, convert_bytes_to_hex


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RPC_URL = 'https://rpc.example.com/v3/a1b2c3d4e5f6a7b8'
IPFS_TOKEN = 'tok_9f8e7d6c5b4a3210'
SECRETS = {
    **variables.PRIVATE_ENV_VARS,
    'EXECUTION_CLIENT_URI': [RPC_URL],
    'LIDO_IPFS_TOKEN': IPFS_TOKEN,
}


def make_record(msg, exc_info=None) -> logging.LogRecord:
    return logging.LogRecord(
        name='test_logger',
        level=logging.INFO,
        pathname='/path/to/test_module.py',
        lineno=10,
        msg=msg,
        args=None,
        exc_info=exc_info,
        func='test_function',
    )


def format_record(record: logging.LogRecord, secrets=None) -> dict:
    """Formats a record the way the root handler of the application does."""
    ValueAsStringFilter().filter(record)
    return json.loads(JsonFormatter(SecretsMasker(SECRETS if secrets is None else secrets)).format(record))


@pytest.mark.unit
class TestLoggingSetup:
    def test_root_logger__after_import__has_masking_handler_with_value_filter(self):
        handlers = [
            handler
            for handler in logging.getLogger().handlers
            if any(isinstance(log_filter, ValueAsStringFilter) for log_filter in handler.filters)
        ]

        assert len(handlers) == 1
        assert isinstance(handlers[0], SafeStreamHandler)
        assert isinstance(handlers[0].formatter, JsonFormatter)
        assert handlers[0].stream is sys.stderr

    @staticmethod
    def _run(code: str) -> list[dict]:
        """Runs the code in a new interpreter with a secret in the environment and returns its log lines."""
        result = subprocess.run(
            [sys.executable, '-c', code],
            cwd=REPO_ROOT,
            env={**os.environ, 'EXECUTION_CLIENT_URI': RPC_URL, 'EXECUTION_CLIENT_URI_FILE': '', 'PYTHONWARNINGS': ''},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.stdout == ''
        assert 'a1b2c3d4e5f6a7b8' not in result.stderr
        return [json.loads(line) for line in result.stderr.splitlines()]

    def test_setup__message_with_a_secret__masked_json_line_on_stderr(self):
        lines = self._run(
            "from src.metrics.logging import logging\n"
            "from src import variables\n"
            "logging.getLogger('test').info({'msg': variables.EXECUTION_CLIENT_URI[0], 'value': 1})\n"
            "logging.getLogger('test').debug('below the level')\n"
        )

        assert len(lines) == 1
        assert lines[0]['msg'] == '***'
        assert lines[0]['value'] == '1'

    def test_setup__unhandled_exception_with_a_secret__masked_json_line(self):
        lines = self._run(
            "import src.metrics.logging\n"
            "from src import variables\n"
            "raise RuntimeError(variables.EXECUTION_CLIENT_URI[0])\n"
        )

        assert len(lines) == 1
        assert lines[0]['levelname'] == 'CRITICAL'
        assert 'RuntimeError: ***' in json.dumps(lines[0])

    def test_setup__warning_with_a_secret__masked_json_line(self):
        lines = self._run(
            "import warnings\n"
            "import src.metrics.logging\n"
            "from src import variables\n"
            "warnings.warn(variables.EXECUTION_CLIENT_URI[0])\n"
        )

        assert len(lines) == 1
        assert lines[0]['levelname'] == 'WARNING'


@pytest.mark.unit
class TestLogLine:
    def test_format__string_message__json_line_with_record_fields(self):
        record = make_record('Test message')

        line = format_record(record)

        assert line == {
            'name': 'test_logger',
            'levelname': 'INFO',
            'funcName': 'test_function',
            'lineno': 10,
            'module': 'test_module',
            'pathname': '/path/to/test_module.py',
            'timestamp': int(record.created),
            'msg': 'Test message',
        }

    def test_format__dict_message__fields_merged_into_line(self):
        record = make_record({'msg': 'Test message', 'key': 'data', 'another_key': 123})

        line = format_record(record)

        assert line['msg'] == 'Test message'
        assert line['key'] == 'data'
        assert line['another_key'] == 123

    def test_format__value_field__converted_to_string(self):
        record = make_record({'msg': 'Test message', 'value': 456})

        line = format_record(record)

        assert line['value'] == '456'

    def test_format__value_field_with_bytes__converted_to_string_with_hex(self):
        record = make_record({'msg': 'Test message', 'value': {'root': b'\xde\xad'}})

        line = format_record(record)

        assert line['value'] == "{'root': '0xdead'}"

    def test_format__value_field_that_cannot_be_converted__logged_as_it_is(self):
        record = make_record({'msg': 'Test message', 'value': {'a': 1}.values()})

        line = format_record(record)

        assert line['value'] == 'dict_values([1])'

    def test_format__bytes_field__converted_to_hex(self):
        record = make_record({'msg': 'Test message', 'root': b'\xde\xad\xbe\xef'})

        line = format_record(record)

        assert line['root'] == '0xdeadbeef'

    def test_format__empty_message__empty_msg_field(self):
        record = make_record('')

        line = format_record(record)

        assert line['msg'] == ''


@pytest.mark.unit
class TestSecretsMasking:
    def test_format__secret_url_in_error_text__masked(self):
        error = f"HTTPSConnectionPool(host='rpc.example.com', port=443): Max retries exceeded with url: {RPC_URL}"
        record = make_record({'msg': 'Request failed.', 'error': error})

        line = json.dumps(format_record(record))

        assert 'a1b2c3d4e5f6a7b8' not in line

    def test_format__secret_path_of_url_in_error_text__masked(self):
        record = make_record('404 Client Error: Not Found for url: /v3/a1b2c3d4e5f6a7b8')

        line = format_record(record)

        assert 'a1b2c3d4e5f6a7b8' not in line['msg']

    def test_format__secret_in_response_body_field__masked(self):
        record = make_record({'msg': 'Invalid response format', 'response': f'{{"token": "{IPFS_TOKEN}"}}'})

        line = format_record(record)

        assert IPFS_TOKEN not in line['response']

    def test_format__secret_in_traceback__masked(self):
        try:
            raise ConnectionError(f'Failed to connect to {RPC_URL}')
        except ConnectionError:
            record = make_record('Request failed.', exc_info=sys.exc_info())

        line = format_record(record)

        assert 'ConnectionError' in line['exc_info']
        assert 'a1b2c3d4e5f6a7b8' not in line['exc_info']


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
