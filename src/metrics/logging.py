import dataclasses
import json
import logging
from typing import Mapping, Iterator, Iterable, Any


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


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.msg if isinstance(record.msg, dict) else {'msg': record.getMessage()}

        message = convert_bytes_to_hex(message)

        if 'value' in message:
            message['value'] = str(message['value'])

        to_json_msg = json.dumps({
            'timestamp': int(record.created),
            'name': record.name,
            'levelname': record.levelname,
            'funcName': record.funcName,
            'lineno': record.lineno,
            'module': record.module,
            'pathname': record.pathname,
            **message,
        })
        return to_json_msg


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())

logging.basicConfig(
    level=logging.INFO,
    handlers=[handler],
)
