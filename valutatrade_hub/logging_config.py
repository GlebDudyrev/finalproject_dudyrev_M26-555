import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

ACTION_LOGGER_NAME = "valutatrade_hub.actions"
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
            return " ".join(parts)

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
        return json.dumps(data, ensure_ascii=False)


def configure_logging(
    log_path: str | Path,
    log_format: str = "text",
    level: int = logging.INFO,
) -> logging.Logger:
    """Configure the application action logger with size-based rotation."""
    if log_format not in ("text", "json"):
        raise ValueError("Формат логирования должен быть 'text' или 'json'")

    file_path = Path(log_path).expanduser()
    file_path.parent.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        file_path,
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        JsonLogFormatter() if log_format == "json" else TextLogFormatter()
    )

    logger = logging.getLogger(ACTION_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    for previous_handler in logger.handlers[:]:
        logger.removeHandler(previous_handler)
        previous_handler.close()

    logger.addHandler(handler)
    return logger
