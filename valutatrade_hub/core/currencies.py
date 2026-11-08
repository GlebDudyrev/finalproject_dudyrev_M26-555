
"""Currency types and the registry of supported currencies."""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

from valutatrade_hub.core.exceptions import CurrencyNotFoundError


@dataclass(frozen=True, slots=True)
class Currency(ABC):
    """Represent a currency with a validated name and ticker."""

    name: str
    code: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Название валюты не может быть пустым")

        if (
            not isinstance(self.code, str)
            or not 2 <= len(self.code) <= 5
            or not self.code.isascii()
            or not self.code.isalnum()
            or not self.code.isupper()
        ):
            raise ValueError("Код валюты должен содержать 2–5 заглавных символов")

    @abstractmethod
    def get_display_info(self) -> str:
        """Return a human-readable description of the currency."""


@dataclass(frozen=True, slots=True)
class FiatCurrency(Currency):
    """Represent a government-issued currency."""

    issuing_country: str

    def __post_init__(self) -> None:
        Currency.__post_init__(self)
        if (
            not isinstance(self.issuing_country, str)
            or not self.issuing_country.strip()
        ):
            raise ValueError("Страна или зона эмиссии не может быть пустой")

    def get_display_info(self) -> str:
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


@dataclass(frozen=True, slots=True)
class CryptoCurrency(Currency):
    """Represent a cryptocurrency with algorithm and market capitalization."""

    algorithm: str
    market_cap: float

    def __post_init__(self) -> None:
        Currency.__post_init__(self)
        if not isinstance(self.algorithm, str) or not self.algorithm.strip():
            raise ValueError("Алгоритм криптовалюты не может быть пустым")
        if (
            isinstance(self.market_cap, bool)
            or not isinstance(self.market_cap, (int, float))
            or not math.isfinite(self.market_cap)
            or self.market_cap < 0
        ):
            raise ValueError("Капитализация должна быть неотрицательным числом")

    def get_display_info(self) -> str:
        market_cap = f"{self.market_cap:.2e}".replace("e+", "e")
        return (
            f"[CRYPTO] {self.code} — {self.name} "
            f"(Algo: {self.algorithm}, MCAP: {market_cap})"
        )


_CURRENCIES: dict[str, Currency] = {
    currency.code: currency
    for currency in (
        FiatCurrency("US Dollar", "USD", "United States"),
        FiatCurrency("Euro", "EUR", "Eurozone"),
        FiatCurrency("Russian Ruble", "RUB", "Russia"),
        FiatCurrency("British Pound", "GBP", "United Kingdom"),
        CryptoCurrency("Bitcoin", "BTC", "SHA-256", 1.12e12),
        CryptoCurrency("Ethereum", "ETH", "Proof of Stake", 4.0e11),
        CryptoCurrency("Solana", "SOL", "Proof of History", 8.0e10),
    )
}


def get_currency(code: str) -> Currency:
    """Return a supported currency or raise CurrencyNotFoundError."""
    try:
        return _CURRENCIES[code]
    except KeyError as error:
        raise CurrencyNotFoundError(code) from error


def get_supported_currency_codes() -> tuple[str, ...]:
    """Return the supported currency codes in alphabetical order."""
    return tuple(sorted(_CURRENCIES))
