"""Reusable logging decorator for domain operations."""

import inspect
import logging
from collections.abc import Callable, Mapping
from functools import wraps
from typing import ParamSpec, TypeVar

from valutatrade_hub.logging_config import ACTION_LOGGER_NAME

P = ParamSpec("P")
R = TypeVar("R")

# Each use case decides which data are safe and useful to include in the log.
LogContext = Callable[[Mapping[str, object], object | None, bool], Mapping[str, object]]


def log_action(
    *,
    context: LogContext | None = None,
    verbose: bool = False,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Log a domain operation while preserving its signature and exceptions.

    ``context`` receives bound call arguments, the successful return value
    (or None on error), and the ``verbose`` flag. It returns event fields.
    Only the fields returned by ``context`` are logged; raw arguments are not.
    """

    def decorate(operation: Callable[P, R]) -> Callable[P, R]:
        operation_signature = inspect.signature(operation)
        logger = logging.getLogger(ACTION_LOGGER_NAME)
        logger.propagate = False
        if not logger.handlers:
            logger.addHandler(logging.NullHandler())

        def log_event(
            arguments: Mapping[str, object],
            value: object | None,
            error: Exception | None,
        ) -> None:
            event = dict(context(arguments, value, verbose)) if context else {}
            event["action"] = operation.__name__.upper()
            event["result"] = "ERROR" if error is not None else "OK"
            if error is not None:
                event["error_type"] = type(error).__name__
                event["error_message"] = str(error)
            logger.info(event["action"], extra={"event": event})

        @wraps(operation)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            bound = operation_signature.bind(*args, **kwargs)
            bound.apply_defaults()
            try:
                value = operation(*args, **kwargs)
            except Exception as error:
                log_event(bound.arguments, None, error)
                raise
            log_event(bound.arguments, value, None)
            return value

        return wrapper

    return decorate
