import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import cast

from valutatrade_hub.core.currencies import CryptoCurrency, get_currency
from valutatrade_hub.core.exceptions import ApiRequestError, CurrencyNotFoundError
from valutatrade_hub.core.models import Portfolio, User
from valutatrade_hub.core.utils import generate_salt, hash_password
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import Storage

INITIAL_BALANCE_USD = 1_000.0

RatesRefresh = Callable[[], object]


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


def _valid_rates(
    snapshot: dict,
    required_pairs: set[str],
    *,
    max_age_seconds: int | None,
    updated_after: datetime | None = None,
) -> tuple[dict, datetime] | None:
    """Validate needed cached quotes and return their oldest timestamp."""
    pairs = snapshot.get("pairs", {})
    if not isinstance(pairs, dict):
        raise ValueError("Некорректная структура rates.json: ожидается 'pairs'")

    now = datetime.now(UTC)
    timestamps = []
    for pair in required_pairs:
        quote = pairs.get(pair)
        if not isinstance(quote, dict):
            return None
        rate = quote.get("rate")
        if (
            isinstance(rate, bool)
            or not isinstance(rate, (int, float))
            or not math.isfinite(rate)
            or rate <= 0
        ):
            return None
        source = quote.get("source")
        if not isinstance(source, str) or not source.strip():
            return None
        if source.strip().lower() == "stub":
            return None  # Historical demo values are not live market quotes.

        timestamp = quote.get("updated_at")
        if not isinstance(timestamp, str):
            return None
        try:
            updated_at = datetime.fromisoformat(timestamp)
        except ValueError:
            return None
        if updated_at.tzinfo is None or updated_at.utcoffset() is None:
            return None

        age = (now - updated_at).total_seconds()
        if age < 0 or (max_age_seconds is not None and age >= max_age_seconds):
            return None
        if updated_after is not None and updated_at <= updated_after:
            return None
        timestamps.append(updated_at)

    return pairs, min(timestamps)


def _get_fresh_rates(
    storage: Storage,
    required_pairs: set[str],
    ttl_seconds: int,
    refresh_rates: RatesRefresh | None = None,
) -> tuple[dict, datetime]:
    """Read the cache, updating through Parser Service only when necessary."""
    if type(ttl_seconds) is not int or ttl_seconds < 0:
        raise ValueError("rates_ttl_seconds должен быть неотрицательным целым числом")
    if not required_pairs:
        return {}, datetime.now(UTC)

    snapshot = storage.get_rates()
    cached = _valid_rates(
        snapshot,
        required_pairs,
        max_age_seconds=ttl_seconds,
    )
    if cached is not None:
        return cached

    if refresh_rates is None:
        raise ApiRequestError("Сервис обновления курсов не настроен")

    refresh_started = datetime.now(UTC)
    refresh_rates()
    refreshed = _valid_rates(
        storage.get_rates(),
        required_pairs,
        max_age_seconds=ttl_seconds if ttl_seconds > 0 else None,
        updated_after=refresh_started if ttl_seconds == 0 else None,
    )
    if refreshed is None:
        raise UseCaseError(
            "Нет актуальных котировок для: " + ", ".join(sorted(required_pairs))
        )
    return refreshed


def get_rate(
    from_currency: str,
    to_currency: str,
    storage: Storage,
    ttl_seconds: int = 300,
    refresh_rates: RatesRefresh | None = None,
) -> tuple[float, datetime]:
    """Return the current exchange rate and its quote timestamp."""
    get_currency(from_currency)
    get_currency(to_currency)

    if from_currency == to_currency:
        return 1.0, datetime.now(UTC)

    required_pairs = {
        f"{code}_USD" for code in (from_currency, to_currency) if code != "USD"
    }
    try:
        pairs, updated_at = _get_fresh_rates(
            storage, required_pairs, ttl_seconds, refresh_rates
        )
    except UseCaseError as error:
        raise UseCaseError(
            f"Курс {from_currency}→{to_currency} недоступен. Повторите попытку позже."
        ) from error

    if not required_pairs.issubset(pairs):
        raise UseCaseError(
            f"Курс {from_currency}→{to_currency} недоступен. Повторите попытку позже."
        )

    from_rate = 1.0 if from_currency == "USD" else pairs[f"{from_currency}_USD"]["rate"]
    to_rate = 1.0 if to_currency == "USD" else pairs[f"{to_currency}_USD"]["rate"]
    rate = from_rate / to_rate
    if not math.isfinite(rate) or rate <= 0:
        raise UseCaseError(f"Курс {from_currency}→{to_currency} некорректен")
    return rate, updated_at


def show_rates(
    storage: Storage,
    currency_code: str | None = None,
    top: int | None = None,
    base_currency: str = "USD",
) -> tuple[list[tuple[str, float, str]], str | None]:
    """Return filtered, converted quotes from the local snapshot only.

    Each row contains the displayed pair, its rate and the original quote
    timestamp. This command does not refresh stale rates through the API.
    """
    get_currency(base_currency)
    if top is not None and (type(top) is not int or top <= 0):
        raise UseCaseError("'top' должен быть положительным целым числом")

    snapshot = storage.get_rates()
    pairs = snapshot.get("pairs")
    if not pairs and (pairs is None or isinstance(pairs, dict)):
        raise UseCaseError(
            "Локальный кеш курсов пуст. Выполните 'update-rates', чтобы загрузить данные."
        )
    if not isinstance(pairs, dict):
        raise UseCaseError("Некорректная структура кеша курсов")

    # All Parser Service quotes are normalized against USD. Keep the
    # conversion in the use case; the CLI only formats the returned rows.
    usd_rates: dict[str, tuple[float, str]] = {}
    for pair, quote in pairs.items():
        if not isinstance(pair, str) or pair.count("_") != 1:
            raise UseCaseError("Некорректная валютная пара в кеше")
        code, to_code = pair.split("_")
        if to_code != "USD":
            continue
        get_currency(code)
        if not isinstance(quote, dict):
            raise UseCaseError(f"Некорректная котировка в кеше: {pair}")
        rate = quote.get("rate")
        updated_at = quote.get("updated_at")
        source = quote.get("source")
        if (
            isinstance(rate, bool)
            or not isinstance(rate, (int, float))
            or not math.isfinite(rate)
            or rate <= 0
            or not isinstance(updated_at, str)
            or not isinstance(source, str)
            or not source.strip()
        ):
            raise UseCaseError(f"Некорректная котировка в кеше: {pair}")
        try:
            timestamp = datetime.fromisoformat(updated_at)
        except ValueError as error:
            raise UseCaseError(f"Некорректная дата котировки: {pair}") from error
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise UseCaseError(f"Некорректная дата котировки: {pair}")
        usd_rates[code] = (float(rate), updated_at)

    if currency_code is not None and currency_code not in usd_rates:
        raise UseCaseError(f"Курс для '{currency_code}' не найден в кеше.")

    base_rate = 1.0
    if base_currency != "USD":
        if base_currency not in usd_rates:
            raise UseCaseError(f"Курс {base_currency}→USD не найден в кеше.")
        base_rate = usd_rates[base_currency][0]

    rows = []
    for code, (rate, updated_at) in usd_rates.items():
        if currency_code is not None and code != currency_code:
            continue
        if top is not None and not isinstance(get_currency(code), CryptoCurrency):
            continue
        converted_rate = rate / base_rate
        if not math.isfinite(converted_rate) or converted_rate <= 0:
            raise UseCaseError(f"Некорректный курс {code}→{base_currency}")
        rows.append((f"{code}_{base_currency}", converted_rate, updated_at))

    if not rows:
        raise UseCaseError("В кеше нет котировок по выбранным фильтрам.")

    if top is None:
        rows.sort(key=lambda entry: entry[0])
    else:
        rows.sort(key=lambda entry: (-entry[1], entry[0]))
        rows = rows[:top]

    last_refresh = snapshot.get("last_refresh")
    if last_refresh is not None:
        if not isinstance(last_refresh, str):
            raise UseCaseError("Некорректная дата обновления кеша")
        try:
            refreshed_at = datetime.fromisoformat(last_refresh)
        except ValueError as error:
            raise UseCaseError("Некорректная дата обновления кеша") from error
        if refreshed_at.tzinfo is None or refreshed_at.utcoffset() is None:
            raise UseCaseError("Некорректная дата обновления кеша")

    return rows, last_refresh


def show_portfolio(
    user: User | None,
    storage: Storage,
    base_currency: str = "USD",
    ttl_seconds: int = 300,
    refresh_rates: RatesRefresh | None = None,
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
    pairs, _ = _get_fresh_rates(storage, required_pairs, ttl_seconds, refresh_rates)

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


def _get_trade_rate(
    currency_code: str,
    storage: Storage,
    ttl_seconds: int,
    refresh_rates: RatesRefresh | None = None,
) -> float:
    """Get a USD quote with an error message for trading commands."""
    try:
        rate, _ = get_rate(currency_code, "USD", storage, ttl_seconds, refresh_rates)
    except UseCaseError as error:
        raise UseCaseError(
            f"Не удалось получить курс для {currency_code}→USD"
        ) from error
    return rate


def _trade_log_context(
    arguments: Mapping[str, object],
    result: object | None,
    verbose: bool,
) -> dict[str, object]:
    """Describe a trade without exposing storage or other call arguments."""
    user = arguments.get("user")
    context: dict[str, object] = {
        "username": user.username if isinstance(user, User) else None,
        "currency_code": arguments.get("currency_code"),
        "amount": arguments.get("amount"),
        "base": "USD",
    }
    if result is not None:
        previous_balance, current_balance, rate = cast(
            tuple[float, float, float], result
        )
        context["rate"] = rate
        if verbose:
            context["before_balance"] = previous_balance
            context["after_balance"] = current_balance
    return context


@log_action(context=_trade_log_context, verbose=True)
def buy(
    user: User | None,
    currency_code: str,
    amount: float,
    storage: Storage,
    ttl_seconds: int = 300,
    refresh_rates: RatesRefresh | None = None,
) -> tuple[float, float, float]:
    """Buy currency using USD and return old balance, new balance, and rate."""
    portfolio = _prepare_trade(user, currency_code, amount, storage)
    rate = _get_trade_rate(currency_code, storage, ttl_seconds, refresh_rates)
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


@log_action(context=_trade_log_context, verbose=True)
def sell(
    user: User | None,
    currency_code: str,
    amount: float,
    storage: Storage,
    ttl_seconds: int = 300,
    refresh_rates: RatesRefresh | None = None,
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

    rate = _get_trade_rate(currency_code, storage, ttl_seconds, refresh_rates)
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
