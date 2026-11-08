import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

ACTION_LOGGER_NAME = "valutatrade_hub.actions"
PARSER_LOGGER_NAME = "valutatrade_hub.parser"
MAX_LOG_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3

# Field names in the event do not depend on any particular use case.
TEXT_FIELDS = (
    ("username", "user"),
    ("user_id", "user_id"),
    ("currency_code", "currency"),
    ("amount", "amount"),
    ("rate", "rate"),
    ("base", "base"),
    ("result", "result"),
    ("error_type", "error_type"),
    ("error_message", "error_message"),
    ("before_balance", "before"),
    ("after_balance", "after"),
)


def _timestamp(record: logging.LogRecord) -> str:
    return (
        datetime.fromtimestamp(record.created, UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _event(record: logging.LogRecord) -> Mapping[str, object]:
    event = getattr(record, "event", None)
    return event if isinstance(event, Mapping) else {}


class TextLogFormatter(logging.Formatter):
    """Format structured events as readable, single-line records."""

    def format(self, record: logging.LogRecord) -> str:
        event = _event(record)
        parts = [record.levelname, _timestamp(record)]
        if not event:
            parts.append(record.getMessage())
            formatted = " ".join(parts)
            if record.exc_info:
                formatted += "\n" + self.formatException(record.exc_info)
            return formatted

        parts.append(str(event.get("action", record.getMessage())))
        for key, label in TEXT_FIELDS:
            value = event.get(key)
            if value is None:
                continue
            rendered = (
                repr(value)
                if isinstance(value, str) and label != "result"
                else str(value)
            )
            parts.append(f"{label}={rendered}")
        return " ".join(parts)


class JsonLogFormatter(logging.Formatter):
    """Format structured events as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, object] = {
            "timestamp": _timestamp(record),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        data.update(_event(record))
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


def _configure_file_logger(
    name: str,
    path: Path,
    log_format: str,
    level: int,
) -> logging.Logger:
    """Create one rotating handler for a dedicated application logger."""
    handler = RotatingFileHandler(
        path,
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        JsonLogFormatter() if log_format == "json" else TextLogFormatter()
    )

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    for previous_handler in logger.handlers[:]:
        logger.removeHandler(previous_handler)
        previous_handler.close()
    logger.addHandler(handler)
    return logger


def configure_logging(
    log_path: str | Path,
    log_format: str = "text",
    level: int = logging.INFO,
) -> logging.Logger:
    """Configure separate rotating action and parser logs in one directory."""
    if log_format not in ("text", "json"):
        raise ValueError("Формат логирования должен быть 'text' или 'json'")

    action_path = Path(log_path).expanduser()
    action_path.parent.mkdir(parents=True, exist_ok=True)
    parser_path = action_path.with_name("parser.log")
    if action_path == parser_path:
        raise ValueError("Для действий и Parser Service нужны разные файлы логов")

    action_logger = _configure_file_logger(
        ACTION_LOGGER_NAME, action_path, log_format, level
    )
    _configure_file_logger(PARSER_LOGGER_NAME, parser_path, log_format, level)
    return action_logger
