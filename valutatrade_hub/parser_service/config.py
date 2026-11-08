"""Configuration for the currency rates parser service."""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from valutatrade_hub.infra.settings import SettingsLoader

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
EXCHANGERATE_API_URL = "https://v6.exchangerate-api.com/v6"

FIAT_CURRENCIES = ("EUR", "GBP", "RUB")
CRYPTO_CURRENCIES = ("BTC", "ETH", "SOL")
CRYPTO_ID_MAP = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}


def _get_exchange_rate_api_key() -> str | None:
    """Read the API key when configuration is created, not at import time."""
    return os.getenv("EXCHANGERATE_API_KEY")


@dataclass(frozen=True, slots=True)
class ParserConfig:
    """Hold parser settings, using the same data directory as Core Service.

    The ExchangeRate-API key is optional at configuration time, allowing the
    CoinGecko client to run independently. The fiat client validates it later.
    """

    data_dir: str | Path | None = None
    exchange_rate_api_key: str | None = field(
        default_factory=_get_exchange_rate_api_key,
        repr=False,
    )
    coingecko_url: str = COINGECKO_URL
    exchange_rate_api_url: str = EXCHANGERATE_API_URL
    base_currency: str = "USD"
    fiat_currencies: tuple[str, ...] = FIAT_CURRENCIES
    crypto_currencies: tuple[str, ...] = CRYPTO_CURRENCIES
    crypto_id_map: dict[str, str] = field(
        default_factory=lambda: CRYPTO_ID_MAP.copy(),
    )
    request_timeout: float = 10.0

    def __post_init__(self) -> None:
        directory = self.data_dir
        if directory is None:
            directory = SettingsLoader().get("data_dir")
        if not isinstance(directory, (str, Path)) or not str(directory).strip():
            raise ValueError("Некорректный путь к каталогу данных")
        object.__setattr__(self, "data_dir", Path(directory).expanduser().resolve())

        key = self.exchange_rate_api_key
        if key is not None and not isinstance(key, str):
            raise ValueError("Некорректный API-ключ ExchangeRate-API")
        normalized_key = key.strip() if key is not None else None
        object.__setattr__(self, "exchange_rate_api_key", normalized_key or None)

        # Core Service stores and combines quotes in the *_USD format.
        if self.base_currency != "USD":
            raise ValueError("Parser Service поддерживает базовую валюту только USD")

        timeout = self.request_timeout
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("request_timeout должен быть положительным числом")

        codes = (self.base_currency, *self.fiat_currencies, *self.crypto_currencies)
        if any(
            not isinstance(code, str)
            or not 2 <= len(code) <= 5
            or not code.isascii()
            or not code.isalpha()
            or not code.isupper()
            for code in codes
        ):
            raise ValueError("Коды валют должны содержать 2–5 заглавных латинских букв")
        if len(codes) != len(set(codes)):
            raise ValueError("Список валют содержит повторяющиеся коды")
        if set(self.crypto_id_map) != set(self.crypto_currencies) or any(
            not isinstance(api_id, str) or not api_id.strip()
            for api_id in self.crypto_id_map.values()
        ):
            raise ValueError("crypto_id_map должен содержать ID каждой криптовалюты")

    @property
    def rates_file_path(self) -> Path:
        """Path to the current rates snapshot read by Core Service."""
        return self.data_dir / "rates.json"

    @property
    def history_file_path(self) -> Path:
        """Path to the parser's historical measurements."""
        return self.data_dir / "exchange_rates.json"
