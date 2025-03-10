import dataclasses
import json
import logging


def convert_bytes_to_hex(data):
    if isinstance(data, bytes):
        return '0x' + data.hex()
    elif dataclasses.is_dataclass(data):
        return convert_bytes_to_hex(dataclasses.asdict(data))
    elif isinstance(data, dict):
        return {key: convert_bytes_to_hex(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [convert_bytes_to_hex(item) for item in data]
    elif isinstance(data, tuple):
        return tuple(convert_bytes_to_hex(item) for item in data)
    return data


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.msg if isinstance(record.msg, dict) else {'msg': record.getMessage()}

        # convert bytes fields of the message to 0x hex strings
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
