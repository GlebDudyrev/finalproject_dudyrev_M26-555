"""API clients for collecting exchange rates."""

import math
from abc import ABC, abstractmethod
from typing import Any

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.parser_service.config import ParserConfig


class BaseApiClient(ABC):
    """Common exchange-rate interface and safe HTTP response validation."""

    def __init__(self, config: ParserConfig) -> None:
        self._config = config

    @abstractmethod
    def fetch_rates(self) -> dict[str, float]:
        """Return validated exchange rates in FROM_TO format."""

    def _get_json(
        self,
        url: str,
        *,
        source: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Request JSON without exposing API keys from request URLs in errors."""
        try:
            response = requests.get(
                url,
                params=params,
                timeout=self._config.request_timeout,
            )
        except requests.exceptions.Timeout:
            raise ApiRequestError(f"{source}: превышено время ожидания") from None
        except requests.exceptions.RequestException:
            raise ApiRequestError(f"{source}: ошибка сети") from None

        if response.status_code in (401, 403):
            raise ApiRequestError(
                f"{source}: ошибка авторизации (HTTP {response.status_code})"
            )
        if response.status_code == 429:
            raise ApiRequestError(f"{source}: превышен лимит запросов (HTTP 429)")
        if response.status_code != 200:
            raise ApiRequestError(f"{source}: HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as error:
            raise ApiRequestError(f"{source}: ответ не является JSON") from error

        if not isinstance(payload, dict):
            raise ApiRequestError(f"{source}: некорректная структура ответа")
        return payload

    @staticmethod
    def _positive_rate(value: Any, source: str, code: str) -> float:
        """Reject nonnumeric, infinite, zero, and negative quotes."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiRequestError(f"{source}: некорректный курс для {code}")
        try:
            rate = float(value)
        except OverflowError as error:
            raise ApiRequestError(f"{source}: некорректный курс для {code}") from error
        if not math.isfinite(rate) or rate <= 0:
            raise ApiRequestError(f"{source}: некорректный курс для {code}")
        return rate


class CoinGeckoClient(BaseApiClient):
    """Get crypto-to-base quotes from CoinGecko's Simple Price API."""

    def fetch_rates(self) -> dict[str, float]:
        config = self._config
        base = config.base_currency
        payload = self._get_json(
            config.coingecko_url,
            source="CoinGecko",
            params={
                "ids": ",".join(
                    config.crypto_id_map[code] for code in config.crypto_currencies
                ),
                "vs_currencies": base.lower(),
            },
        )
        if "error" in payload:
            raise ApiRequestError("CoinGecko: API вернул ошибку")

        rates = {}
        for code in config.crypto_currencies:
            coin = payload.get(config.crypto_id_map[code])
            if not isinstance(coin, dict):
                raise ApiRequestError(f"CoinGecko: отсутствуют данные для {code}")
            rates[f"{code}_{base}"] = self._positive_rate(
                coin.get(base.lower()), "CoinGecko", code
            )
        return rates


class ExchangeRateApiClient(BaseApiClient):
    """Get fiat-to-base quotes from ExchangeRate-API."""

    def fetch_rates(self) -> dict[str, float]:
        config = self._config
        key = config.exchange_rate_api_key
        if not key:
            raise ApiRequestError("ExchangeRate-API: API-ключ не задан")

        base = config.base_currency
        url = f"{config.exchange_rate_api_url.rstrip('/')}/{key}/latest/{base}"
        payload = self._get_json(url, source="ExchangeRate-API")
        if payload.get("result") != "success":
            error_type = payload.get("error-type")
            if error_type == "quota-reached":
                reason = "превышен лимит запросов"
            elif error_type in ("invalid-key", "inactive-account"):
                reason = "недействительный или неактивный API-ключ"
            else:
                reason = "API вернул ошибку"
            raise ApiRequestError(f"ExchangeRate-API: {reason}")

        if payload.get("base_code") != base:
            raise ApiRequestError("ExchangeRate-API: неожиданная базовая валюта")

        # The v6 API uses conversion_rates; the assignment shows rates.
        quotes = payload.get("conversion_rates")
        if quotes is None:
            quotes = payload.get("rates")
        if not isinstance(quotes, dict):
            raise ApiRequestError("ExchangeRate-API: отсутствует словарь курсов")

        rates = {}
        for code in config.fiat_currencies:
            # Provider supplies BASE -> CODE, while the cache needs CODE -> BASE.
            base_to_code = self._positive_rate(
                quotes.get(code), "ExchangeRate-API", code
            )
            rate = 1.0 / base_to_code
            rates[f"{code}_{base}"] = self._positive_rate(
                rate, "ExchangeRate-API", code
            )
        return rates
