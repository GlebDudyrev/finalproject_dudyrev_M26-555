import json
import logging
import time
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

ACTION_LOGGER_NAME = "valutatrade_hub.actions"
MAX_LOG_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3


class JsonLogFormatter(logging.Formatter):
    """Format log records as JSON with UTC timestamps."""

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="seconds"
            ),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)

        return json.dumps(data, ensure_ascii=False)


def configure_logging(
    log_path: str | Path,
    log_format: str = "text",
    level: int = logging.INFO,
) -> logging.Logger:
    """Configure a rotating file logger for application actions."""
    if log_format not in ("text", "json"):
        raise ValueError("Формат логирования должен быть 'text' или 'json'")

    file_path = Path(log_path).expanduser()
    file_path.parent.mkdir(parents=True, exist_ok=True)

    if log_format == "json":
        formatter = JsonLogFormatter()
    else:
        formatter = logging.Formatter(
            "%(levelname)s %(asctime)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        formatter.converter = time.gmtime

    handler = RotatingFileHandler(
        file_path,
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)

    logger = logging.getLogger(ACTION_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    # Reconfiguration must not duplicate log entries or leave files open.
    for previous_handler in logger.handlers[:]:
        logger.removeHandler(previous_handler)
        previous_handler.close()

    logger.addHandler(handler)
    return logger
