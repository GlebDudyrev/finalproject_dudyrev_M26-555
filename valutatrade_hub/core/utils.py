import hashlib
import secrets

HASH_ITERATIONS = 600_000

EXCHANGE_RATES_USD = {
    "USD": 1.0,
    "EUR": 1.0786,
    "BTC": 59337.21,
    "RUB": 0.01016,
    "ETH": 3720.0,
}


def generate_salt() -> str:
    """Generate a cryptographically secure random salt."""

    return secrets.token_hex(16)


def hash_password(password: str, salt: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256."""

    return hashlib.pbkdf2_hmac(
        hash_name="sha256",
        password=password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        iterations=HASH_ITERATIONS,
    ).hex()


def get_exchange_rate(from_currency: str, to_currency: str) -> float:
    """Return the exchange rate between two currencies."""

    try:
        from_rate = EXCHANGE_RATES_USD[from_currency]
        to_rate = EXCHANGE_RATES_USD[to_currency]
    except (KeyError, TypeError) as error:
        raise ValueError("Неизвестная валюта") from error

    return from_rate / to_rate
