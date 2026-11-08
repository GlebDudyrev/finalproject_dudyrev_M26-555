import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.parser_service.api_clients import BaseApiClient
from valutatrade_hub.parser_service.storage import ParserStorage

LOGGER_NAME = "valutatrade_hub.parser"
logger = logging.getLogger(LOGGER_NAME)
logger.addHandler(logging.NullHandler())


@dataclass(frozen=True, slots=True)
class UpdateResult:
    """Summarize one update attempt, including partial provider failures."""

    fetched: int
    updated: int
    history_added: int
    last_refresh: str | None
    errors: dict[str, str] = field(default_factory=dict)


class RatesUpdater:
    """Fetch quotes from independent providers and update parser storage.

    ``clients`` maps source names to clients, for example
    ``{"CoinGecko": CoinGeckoClient(config)}``. Source names are also saved
    in the quote metadata. One provider failure does not block the others.
    """

    def __init__(
        self,
        clients: Mapping[str, BaseApiClient],
        storage: ParserStorage,
    ) -> None:
        if not clients:
            raise ValueError("Не указан ни один источник котировок")
        if any(not isinstance(name, str) or not name.strip() for name in clients):
            raise ValueError("У каждого источника должно быть непустое имя")

        self._clients = dict(clients)
        self._storage = storage

    def run_update(self, source: str | None = None) -> UpdateResult:
        """Fetch and persist rates, optionally from one selected source.

        API failures are recorded and other providers are still queried.
        If every provider fails, raise ApiRequestError without modifying files.
        Unexpected errors, including storage failures, are propagated.
        """
        if source is None:
            selected = self._clients.items()
        else:
            if source not in self._clients:
                raise ValueError(f"Неизвестный источник котировок: {source}")
            selected = ((source, self._clients[source]),)

        # Do not query providers or modify history when the cache is damaged.
        self._storage.get_rates()

        logger.info("Starting rates update")
        quotes: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}

        for name, client in selected:
            logger.info("Fetching rates from %s", name)
            try:
                rates = client.fetch_rates()
                if not rates:
                    raise ApiRequestError(f"{name}: получен пустой набор котировок")
            except ApiRequestError as error:
                errors[name] = str(error)
                logger.error("Failed to fetch from %s: %s", name, error)
                continue

            fetched_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            for pair, rate in rates.items():
                if pair in quotes:
                    raise ValueError(f"Пара {pair} получена из нескольких источников")
                quotes[pair] = {
                    "rate": rate,
                    "updated_at": fetched_at,
                    "source": name,
                }
            logger.info("Fetched %d rates from %s", len(rates), name)

        if not quotes:
            logger.error("Rates update failed: no providers returned rates")
            raise ApiRequestError("Не удалось получить курсы ни от одного источника")

        # History first: a failed history write must not advance the snapshot.
        logger.info("Saving %d measurements to history", len(quotes))
        try:
            history_added = self._storage.append_history(quotes)
        except (OSError, ValueError, TypeError) as error:
            logger.error("Failed to save rates history: %s", error)
            raise

        refreshed_at = datetime.now(UTC)
        logger.info("Updating current snapshot with %d rates", len(quotes))
        try:
            updated = self._storage.update_rates(quotes, refreshed_at=refreshed_at)
        except (OSError, ValueError, TypeError) as error:
            logger.error("Failed to update rates snapshot: %s", error)
            raise
        last_refresh = (
            refreshed_at.isoformat().replace("+00:00", "Z") if updated else None
        )

        logger.info(
            "Rates update complete: fetched=%d updated=%d history_added=%d "
            "failed_sources=%d",
            len(quotes),
            updated,
            history_added,
            len(errors),
        )
        return UpdateResult(
            fetched=len(quotes),
            updated=updated,
            history_added=history_added,
            last_refresh=last_refresh,
            errors=errors,
        )
