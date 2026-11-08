"""Periodically refresh exchange rates without blocking the interactive CLI."""

import logging
import math
import threading
from collections.abc import Callable

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.parser_service.updater import UpdateResult

LOGGER_NAME = "valutatrade_hub.parser"


class RatesScheduler:
    """Run periodic updates and serialize them with manual CLI updates.

    The first scheduled update occurs after ``interval_seconds``. Manual
    updates and cache-triggered updates use ``run_update`` and share the
    same lock, so this process never writes the rates files concurrently.
    """

    def __init__(
        self,
        update_rates: Callable[[str | None], UpdateResult],
        interval_seconds: float,
    ) -> None:
        if (
            isinstance(interval_seconds, bool)
            or not isinstance(interval_seconds, (int, float))
            or not math.isfinite(interval_seconds)
            or interval_seconds <= 0
        ):
            raise ValueError("Интервал обновления должен быть положительным числом")

        self._update_rates = update_rates
        self._interval_seconds = interval_seconds
        self._update_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._logger = logging.getLogger(LOGGER_NAME)

    def run_update(self, source: str | None = None) -> UpdateResult:
        """Perform an update, preventing overlapping scheduled/CLI updates."""
        with self._update_lock:
            return self._update_rates(source)

    def start(self) -> None:
        """Start a daemon worker; do nothing if it is already running."""
        if self._thread is not None and self._thread.is_alive():
            if self._stop_event.is_set():
                raise RuntimeError("Планировщик ещё завершает работу")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="valutatrade-rates-scheduler",
            daemon=True,
        )
        self._thread.start()
        self._logger.info(
            "Rates scheduler started (interval=%s seconds)",
            self._interval_seconds,
        )

    def stop(self) -> None:
        """Request shutdown and wait for an in-flight update to finish."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join()
        if thread is not None:
            self._logger.info("Rates scheduler stopped")

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            try:
                result = self.run_update()
            except ApiRequestError as error:
                self._logger.warning("Scheduled rates update failed: %s", error)
            except Exception:
                # Keep the worker alive, but preserve the unexpected traceback.
                self._logger.exception("Unexpected scheduled rates update failure")
            else:
                self._logger.info(
                    "Scheduled rates update finished: fetched=%d updated=%d "
                    "failed_sources=%d",
                    result.fetched,
                    result.updated,
                    len(result.errors),
                )
