import json
import math
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from valutatrade_hub.parser_service.config import ParserConfig


def _utc_timestamp(value: datetime | str) -> str:
    """Normalize an aware ISO timestamp to UTC without losing microseconds."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError("Некорректная дата котировки") from error

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Дата котировки должна содержать часовой пояс")
    if value.utcoffset() is None:
        raise ValueError("Дата котировки должна содержать часовой пояс")

    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _validate_pair(pair: str) -> tuple[str, str]:
    if not isinstance(pair, str) or pair.count("_") != 1:
        raise ValueError(f"Некорректная валютная пара: {pair!r}")

    from_code, to_code = pair.split("_")
    if any(
        not 2 <= len(code) <= 5
        or not code.isascii()
        or not code.isalpha()
        or not code.isupper()
        for code in (from_code, to_code)
    ):
        raise ValueError(f"Некорректная валютная пара: {pair!r}")
    return from_code, to_code


def _normalize_quotes(
    quotes: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Validate provider metadata before it reaches either JSON file."""
    if not isinstance(quotes, Mapping):
        raise ValueError("Котировки должны быть словарём валютных пар")

    result = {}
    for pair, entry in quotes.items():
        _validate_pair(pair)
        if not isinstance(entry, Mapping):
            raise ValueError(f"Некорректная запись для {pair}")

        rate = entry.get("rate")
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            raise ValueError(f"Некорректный курс для {pair}")
        try:
            rate = float(rate)
        except OverflowError as error:
            raise ValueError(f"Некорректный курс для {pair}") from error
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError(f"Некорректный курс для {pair}")

        timestamp = _utc_timestamp(entry.get("updated_at"))
        source = entry.get("source")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"Не указан источник котировки {pair}")

        meta = entry.get("meta", {})
        if not isinstance(meta, dict):
            raise ValueError(f"Некорректные метаданные для {pair}")

        result[pair] = {
            "rate": float(rate),
            "updated_at": timestamp,
            "source": source.strip(),
            "meta": meta.copy(),
        }
    return result


def _read_json(path: Path, default: Any) -> Any:
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return default


def _write_json_atomic(path: Path, data: object) -> None:
    """Write a complete JSON document before replacing its previous version."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())

        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class ParserStorage:
    """Store immutable measurements and a latest-per-pair JSON snapshot.

    Both files are replaced atomically *individually*. The caller coordinates
    the history and snapshot operations; there is no two-file transaction.
    """

    def __init__(self, config: ParserConfig) -> None:
        self._history_path = config.history_file_path
        self._rates_path = config.rates_file_path

    def get_history(self) -> list[dict[str, Any]]:
        """Return the historical measurements, or an empty list if absent."""
        history = _read_json(self._history_path, [])
        if not isinstance(history, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("id"), str)
            for item in history
        ):
            raise ValueError("Некорректная структура exchange_rates.json")
        identifiers = [item["id"] for item in history]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("История котировок содержит повторяющиеся ID")
        return history

    def append_history(self, quotes: Mapping[str, Mapping[str, Any]]) -> int:
        """Append unique measurements; never overwrite an existing history ID."""
        normalized = _normalize_quotes(quotes)
        history = self.get_history()
        known = {entry["id"]: entry for entry in history}
        additions = []

        for pair, quote in normalized.items():
            from_code, to_code = _validate_pair(pair)
            timestamp = quote["updated_at"]
            record = {
                "id": f"{pair}_{timestamp}",
                "from_currency": from_code,
                "to_currency": to_code,
                "rate": quote["rate"],
                "timestamp": timestamp,
                "source": quote["source"],
                "meta": quote["meta"],
            }
            existing = known.get(record["id"])
            if existing is not None:
                if existing != record:
                    raise ValueError(f"Конфликт измерений с ID {record['id']}")
                continue
            known[record["id"]] = record
            additions.append(record)

        if additions:
            _write_json_atomic(self._history_path, [*history, *additions])
        return len(additions)

    def get_rates(self) -> dict[str, Any]:
        """Read the Core Service snapshot, including its update timestamp."""
        snapshot = _read_json(
            self._rates_path,
            {"pairs": {}, "last_refresh": None},
        )
        if snapshot == {}:
            # An empty file is a valid initial state of the Core Service.
            return {"pairs": {}, "last_refresh": None}
        if not isinstance(snapshot, dict) or not isinstance(
            snapshot.get("pairs"), dict
        ):
            raise ValueError("Некорректная структура rates.json")
        _normalize_quotes(snapshot["pairs"])
        if snapshot.get("last_refresh") is not None:
            _utc_timestamp(snapshot["last_refresh"])
        return snapshot

    def update_rates(
        self,
        quotes: Mapping[str, Mapping[str, Any]],
        *,
        refreshed_at: datetime | str | None = None,
    ) -> int:
        """Update a pair only when its timestamp is strictly newer."""
        normalized = _normalize_quotes(quotes)
        snapshot = self.get_rates()
        pairs = snapshot["pairs"].copy()
        updated = 0

        for pair, quote in normalized.items():
            previous = pairs.get(pair)
            if previous is not None:
                if not isinstance(previous, dict):
                    raise ValueError(f"Некорректная сохранённая котировка {pair}")
                old_timestamp = _utc_timestamp(previous.get("updated_at"))
                if datetime.fromisoformat(
                    quote["updated_at"]
                ) <= datetime.fromisoformat(old_timestamp):
                    continue

            pairs[pair] = {
                "rate": quote["rate"],
                "updated_at": quote["updated_at"],
                "source": quote["source"],
            }
            updated += 1

        if updated:
            refreshed_at = datetime.now(UTC) if refreshed_at is None else refreshed_at
            _write_json_atomic(
                self._rates_path,
                {
                    "pairs": pairs,
                    "last_refresh": _utc_timestamp(refreshed_at),
                },
            )
        return updated
