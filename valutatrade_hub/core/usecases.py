import math
from datetime import UTC, datetime

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import CurrencyNotFoundError
from valutatrade_hub.core.models import Portfolio, User
from valutatrade_hub.core.utils import EXCHANGE_RATES_USD, generate_salt, hash_password
from valutatrade_hub.infra.database import Storage

INITIAL_BALANCE_USD = 1_000.0


class UseCaseError(Exception):
    """Indicate an expected business operation failure."""


def register(username: str, password: str, storage: Storage) -> User:
    """Register a user and create their initial portfolio."""
    if not isinstance(username, str) or not username.strip():
        raise UseCaseError("Имя пользователя не может быть пустым")

    if not isinstance(password, str) or len(password) < 4:
        raise UseCaseError("Пароль должен быть не короче 4 символов")

    username = username.strip()
    if storage.get_user(username) is not None:
        raise UseCaseError(f"Имя пользователя '{username}' уже занято")

    salt = generate_salt()

    user = User(
        user_id=storage.get_next_user_id(),
        username=username,
        hashed_password=hash_password(password, salt),
        salt=salt,
        registration_date=datetime.now(UTC),
    )

    portfolio = Portfolio(user)
    portfolio.add_currency("USD").deposit(INITIAL_BALANCE_USD)

    storage.add_user(user)
    storage.add_portfolio(portfolio)

    return user


def login(username: str, password: str, storage: Storage) -> User:
    """Authenticate a user and return their account."""
    if not isinstance(username, str) or not username.strip():
        raise UseCaseError("Имя пользователя не может быть пустым")

    username = username.strip()
    user = storage.get_user(username)

    if user is None:
        raise UseCaseError(f"Пользователь '{username}' не найден")

    if not user.verify_password(password):
        raise UseCaseError("Неверный пароль")

    return user


def _get_fresh_rates(
    storage: Storage,
    required_pairs: set[str],
    ttl_seconds: int,
) -> tuple[dict, datetime]:
    """Return fresh USD quotes, refreshing the snapshot if necessary."""
    now = datetime.now(UTC)
    snapshot = storage.get_rates()
    pairs = snapshot.get("pairs", {})

    if required_pairs.issubset(pairs):
        timestamps = [
            datetime.fromisoformat(pairs[key]["updated_at"]) for key in required_pairs
        ]
        timestamps = [
            value if value.tzinfo is not None else value.replace(tzinfo=UTC)
            for value in timestamps
        ]
        if all(
            0 <= (now - value).total_seconds() < ttl_seconds for value in timestamps
        ):
            return pairs, min(timestamps, default=now)

    pairs = {
        f"{code}_USD": {
            "rate": rate,
            "updated_at": now.isoformat(),
            "source": "Stub",
        }
        for code, rate in EXCHANGE_RATES_USD.items()
        if code != "USD"
    }
    if required_pairs.issubset(pairs):
        storage.update_rates({"pairs": pairs, "last_refresh": now.isoformat()})

    return pairs, now


def get_rate(
    from_currency: str,
    to_currency: str,
    storage: Storage,
    ttl_seconds: int = 300,
) -> tuple[float, datetime]:
    """Return the current exchange rate and its quote timestamp."""
    get_currency(from_currency)
    get_currency(to_currency)

    if from_currency == to_currency:
        return 1.0, datetime.now(UTC)

    required_pairs = {
        f"{code}_USD" for code in (from_currency, to_currency) if code != "USD"
    }
    pairs, updated_at = _get_fresh_rates(storage, required_pairs, ttl_seconds)

    if not required_pairs.issubset(pairs):
        raise UseCaseError(
            f"Курс {from_currency}→{to_currency} недоступен. Повторите попытку позже."
        )

    from_rate = 1.0 if from_currency == "USD" else pairs[f"{from_currency}_USD"]["rate"]
    to_rate = 1.0 if to_currency == "USD" else pairs[f"{to_currency}_USD"]["rate"]
    return from_rate / to_rate, updated_at


def show_portfolio(
    user: User | None,
    storage: Storage,
    base_currency: str = "USD",
    ttl_seconds: int = 300,
) -> tuple[list[tuple[str, float, float]], float]:
    """Return wallet balances, converted values and the total portfolio value."""
    if user is None:
        raise UseCaseError("Сначала выполните login")

    try:
        get_currency(base_currency)
    except CurrencyNotFoundError as error:
        raise UseCaseError(f"Неизвестная базовая валюта '{base_currency}'") from error

    portfolio = storage.get_portfolio(user)
    if portfolio is None:
        raise UseCaseError(f"Портфель пользователя '{user.username}' не найден")

    if not portfolio.wallets:
        return [], 0.0

    currencies = set(portfolio.wallets) | {base_currency}
    required_pairs = {f"{code}_USD" for code in currencies if code != "USD"}
    pairs, _ = _get_fresh_rates(storage, required_pairs, ttl_seconds)

    if missing_pairs := required_pairs - pairs.keys():
        missing_currency = sorted(missing_pairs)[0].removesuffix("_USD")
        raise UseCaseError(
            f"Курс {missing_currency}→USD недоступен. Повторите попытку позже."
        )

    exchange_rates = {"USD": 1.0}
    exchange_rates.update(
        {code: pairs[f"{code}_USD"]["rate"] for code in currencies if code != "USD"}
    )

    base_rate = exchange_rates[base_currency]
    wallet_values = [
        (code, wallet.balance, wallet.balance * exchange_rates[code] / base_rate)
        for code, wallet in portfolio.wallets.items()
    ]
    total = portfolio.get_total_value(base_currency, exchange_rates)

    return wallet_values, total


def _prepare_trade(
    user: User | None,
    currency_code: str,
    amount: float,
    storage: Storage,
) -> Portfolio:
    """Validate a trade and return the user's portfolio."""
    if user is None:
        raise UseCaseError("Сначала выполните login")

    get_currency(currency_code)
    if (
        isinstance(amount, bool)
        or not isinstance(amount, (int, float))
        or not math.isfinite(amount)
        or amount <= 0
    ):
        raise UseCaseError("'amount' должен быть положительным числом")

    if currency_code == "USD":
        raise UseCaseError("Нельзя покупать или продавать USD за USD")

    portfolio = storage.get_portfolio(user)
    if portfolio is None:
        raise UseCaseError(f"Портфель пользователя '{user.username}' не найден")

    return portfolio


def _get_trade_rate(currency_code: str, storage: Storage, ttl_seconds: int) -> float:
    """Get a USD quote with an error message for trading commands."""
    try:
        rate, _ = get_rate(currency_code, "USD", storage, ttl_seconds)
    except UseCaseError as error:
        raise UseCaseError(
            f"Не удалось получить курс для {currency_code}→USD"
        ) from error
    return rate


def buy(
    user: User | None,
    currency_code: str,
    amount: float,
    storage: Storage,
    ttl_seconds: int = 300,
) -> tuple[float, float, float]:
    """Buy currency using USD and return old balance, new balance, and rate."""
    portfolio = _prepare_trade(user, currency_code, amount, storage)
    rate = _get_trade_rate(currency_code, storage, ttl_seconds)
    cost = amount * rate
    if not math.isfinite(cost):
        raise UseCaseError("Стоимость покупки слишком велика")

    try:
        usd_wallet = portfolio.get_wallet("USD")
    except KeyError as error:
        raise UseCaseError("USD-кошелёк не найден") from error

    usd_wallet.withdraw(cost)

    try:
        wallet = portfolio.get_wallet(currency_code)
    except KeyError:
        wallet = portfolio.add_currency(currency_code)

    previous_balance = wallet.balance
    wallet.deposit(amount)
    storage.update_portfolio(portfolio)

    return previous_balance, wallet.balance, rate


def sell(
    user: User | None,
    currency_code: str,
    amount: float,
    storage: Storage,
    ttl_seconds: int = 300,
) -> tuple[float, float, float]:
    """Sell currency for USD and return old balance, new balance, and rate."""
    portfolio = _prepare_trade(user, currency_code, amount, storage)

    try:
        wallet = portfolio.get_wallet(currency_code)
    except KeyError as error:
        raise UseCaseError(
            f"У вас нет кошелька '{currency_code}'. Добавьте валюту: "
            "она создаётся автоматически при первой покупке."
        ) from error

    previous_balance = wallet.balance
    wallet.withdraw(amount)

    rate = _get_trade_rate(currency_code, storage, ttl_seconds)
    revenue = amount * rate
    if not math.isfinite(revenue):
        raise UseCaseError("Стоимость продажи слишком велика")

    try:
        usd_wallet = portfolio.get_wallet("USD")
    except KeyError:
        usd_wallet = portfolio.add_currency("USD")

    usd_wallet.deposit(revenue)
    storage.update_portfolio(portfolio)

    return previous_balance, wallet.balance, rate
