import hmac
import math
from datetime import datetime

from valutatrade_hub.core.utils import EXCHANGE_RATES_USD, generate_salt, hash_password


class User:
    """Represent a user and manage their credentials."""

    def __init__(
        self,
        user_id: int,
        username: str,
        hashed_password: str,
        salt: str,
        registration_date: datetime,
    ) -> None:
        if type(user_id) is not int or user_id <= 0:
            raise ValueError("ID пользователя должен быть положительным целым числом")

        if not isinstance(hashed_password, str) or not hashed_password:
            raise ValueError("Хеш пароля не может быть пустым")

        if not isinstance(salt, str) or not salt:
            raise ValueError("Соль не может быть пустой")

        if not isinstance(registration_date, datetime):
            raise TypeError("Дата регистрации должна иметь тип datetime")

        self._user_id = user_id
        self._username = username
        self._hashed_password = hashed_password
        self._salt = salt
        self._registration_date = registration_date

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def username(self) -> str:
        return self._username

    @username.setter
    def username(self, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Имя пользователя не может быть пустым")

        self._username = value.strip()

    @property
    def hashed_password(self) -> str:
        return self._hashed_password

    @property
    def salt(self) -> str:
        return self._salt

    @property
    def registration_date(self) -> datetime:
        return self._registration_date

    def get_user_info(self) -> dict[str, int | str]:
        """Return user information without credentials."""

        return {
            "user_id": self._user_id,
            "username": self._username,
            "registration_date": self._registration_date.isoformat(),
        }

    def change_password(self, new_password: str) -> None:
        """Change the password using a newly generated salt."""

        if not isinstance(new_password, str) or len(new_password) < 4:
            raise ValueError("Пароль должен быть не короче 4 символов")

        salt = generate_salt()
        hashed_password = hash_password(new_password, salt)

        self._salt = salt
        self._hashed_password = hashed_password

    def verify_password(self, password: str) -> bool:
        """Verify a password against the stored hash."""

        if not isinstance(password, str):
            return False

        hashed_password = hash_password(password, self._salt)
        return hmac.compare_digest(hashed_password, self._hashed_password)


class Wallet:
    """Represent a wallet holding a single currency."""

    def __init__(
        self,
        currency_code: str,
    ) -> None:
        if (
            not isinstance(currency_code, str)
            or not currency_code.isupper()
            or currency_code != currency_code.strip()
        ):
            raise ValueError("Некорректный код валюты")

        self._currency_code = currency_code
        self._balance = 0.0

    @property
    def _currency_code(self) -> str:
        return self._currency_code

    @property
    def balance(self) -> float:
        return self._balance

    @balance.setter
    def balance(self, value: float) -> None:
        self._validate_number(value)

        if value < 0:
            raise ValueError("Баланс не может быть отрицательным")

        self._balance = float(value)

    @staticmethod
    def _validate_number(value: float) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("Значение должно быть конечным числом")

    @classmethod
    def _validate_amount(cls, amount: float) -> None:
        cls._validate_number(amount)

        if amount <= 0:
            raise ValueError("'amount' должен быть положительным числом")

    def deposit(self, amount: float) -> None:
        """Increase the wallet balance."""

        self._validate_amount(amount)
        self.balance += amount

    def withdraw(self, amount: float) -> None:
        """Decrease the wallet balance if sufficient funds are available."""

        self._validate_amount(amount)

        if amount > self.balance:
            raise ValueError("Недостаточно средств")

        self.balance -= amount

    def get_balance_info(self) -> dict[str, str | float]:
        """Return the wallet currency and current balance."""

        return {
            "currency_code": self.currency_code,
            "balance": self.balance,
        }


class Portfolio:
    """Manage the wallets belonging to a user."""

    def __init__(
        self,
        user: User,
        wallets: dict[str, Wallet] | None = None,
    ) -> None:
        if not isinstance(user, User):
            raise TypeError("Владелец портфеля должен быть объектом User")

        if wallets is not None and not isinstance(wallets, dict):
            raise TypeError("Кошельки должны быть представлены словарём")

        for currency_code, wallet in (wallets or {}).items():
            if (
                not isinstance(wallet, Wallet)
                or currency_code != wallet.currency_code
            ):
                raise ValueError("Некорректные данные кошелька")

        self._user = user
        self._wallets = wallets.copy() if wallets is not None else {}

    @property
    def user(self) -> User:
        return self._user

    @property
    def user_id(self) -> int:
        return self._user.user_id

    @property
    def wallets(self) -> dict[str, Wallet]:
        return self._wallets.copy()

    def add_currency(self, currency_code: str) -> Wallet:
        """Add a new wallet for the specified currency."""

        if currency_code in self._wallets:
            raise ValueError(f"Кошелёк '{currency_code}' уже существует")

        wallet = Wallet(currency_code)
        self._wallets[currency_code] = wallet

        return wallet

    def get_wallet(self, currency_code: str) -> Wallet:
        """Return the wallet for the specified currency."""

        return self._wallets[currency_code]

def get_total_value(
    self,
    base_currency: str = "USD",
    exchange_rates: dict[str, float] = EXCHANGE_RATES_USD,
) -> float:
    """Calculate the total portfolio value in the base currency."""

    if base_currency not in exchange_rates:
        raise ValueError(f"Неизвестная валюта '{base_currency}'")

    base_rate = exchange_rates[base_currency]

    total_usd = sum(
        wallet.balance * exchange_rates[wallet.currency_code]
        for wallet in self._wallets.values()
    )

    return total_usd / base_rate