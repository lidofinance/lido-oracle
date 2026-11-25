import dataclasses
import logging
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from logmask import setup_logging

from src import variables


def convert_bytes_to_hex(data: Any) -> Any:
    if isinstance(data, bytes):
        return '0x' + data.hex()
    if dataclasses.is_dataclass(data):
        return convert_bytes_to_hex(dataclasses.asdict(data))  # type: ignore[arg-type]
    if isinstance(data, Mapping):
        return {key: convert_bytes_to_hex(value) for key, value in data.items()}
    if isinstance(data, Iterator):
        return (convert_bytes_to_hex(item) for item in data)
    if isinstance(data, Iterable) and not isinstance(data, (str, bytes)):
        return type(data)(convert_bytes_to_hex(item) for item in data)  # type: ignore
    return data


class ValueAsStringFilter(logging.Filter):
    """Log consumers get the `value` field of a dict message as a string, whatever its type is."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, dict) and 'value' in record.msg:
            record.msg = {**record.msg, 'value': self._as_string(record.msg['value'])}
        return True

    @staticmethod
    def _as_string(value: Any) -> str:
        try:
            return str(convert_bytes_to_hex(value))
        except Exception:  # an error here would reach the caller of the logger
            return str(value)


# JSON lines to stderr; every line, traceback and warning goes through the masker of the secrets.
setup_logging(variables.LOG_SECRETS, level=logging.INFO)

for handler in logging.getLogger().handlers:
    handler.addFilter(ValueAsStringFilter())
