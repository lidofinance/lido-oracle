import json
import logging
from typing import Any


def _extract_message(record: logging.LogRecord) -> dict[str, Any]:
    """
    Extracts and processes the log message from the log record.

    Args:
        record (logging.LogRecord): The log record to process.

    Returns:
        Dict[str, Any]: The processed message as a dictionary.
    """
    # Extract message, converting it to a dict if it's not already one
    if isinstance(record.msg, dict):
        message = record.msg
    else:
        message = {'msg': record.getMessage()}

    # Convert 'value' field to string if it exists
    if 'value' in message:
        message['value'] = str(message['value'])

    return message


def _build_log_record(record: logging.LogRecord, message: dict[str, Any]) -> dict[str, Any]:
    """
    Builds a dictionary of log record fields including the processed message.

    Args:
        record (logging.LogRecord): The original log record.
        message (Dict[str, Any]): The processed message.

    Returns:
        Dict[str, Any]: The complete log record to be serialized as JSON.
    """
    return {
        'timestamp': int(record.created),
        'name': record.name,
        'levelname': record.levelname,
        'funcName': record.funcName,
        'lineno': record.lineno,
        'module': record.module,
        'pathname': record.pathname,
        **message,
    }


class JsonFormatter(logging.Formatter):
    """
    A custom logging formatter that formats log records into JSON strings.
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Format a log record into a JSON string.

        Args:
            record (logging.LogRecord): The log record to format.

        Returns:
            str: The formatted log record as a JSON string.
        """
        try:
            message = _extract_message(record)
            log_record = _build_log_record(record, message)
            return json.dumps(log_record)
        except (TypeError, ValueError) as e:
            # Handle JSON serialization errors gracefully
            logging.error(f"Failed to format log record: {e}")
            return f"Failed to format log record: {e}"


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())

logging.basicConfig(
    level=logging.INFO,
    handlers=[handler],
)
