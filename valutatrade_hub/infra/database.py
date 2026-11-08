from datetime import datetime
from pathlib import Path
from typing import ClassVar, Protocol, Self, TypeVar

from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.infra.utils import read_json_file, write_json_file

JSONData = TypeVar("JSONData", list, dict)


class Storage(Protocol):
    """Define CRUD operations for application data."""

    def add_user(self, user: User) -> None: ...

    def get_user(self, username: str) -> User | None: ...

    def update_user(self, user: User) -> None: ...

    def delete_user(self, user_id: int) -> None: ...

    def add_portfolio(self, portfolio: Portfolio) -> None: ...

    def get_portfolio(self, user: User) -> Portfolio | None: ...

    def update_portfolio(self, portfolio: Portfolio) -> None: ...

    def delete_portfolio(self, user_id: int) -> None: ...

    def get_next_user_id(self) -> int: ...

    def get_rates(self) -> dict: ...

    def update_rates(self, rates: dict) -> None: ...


class JsonStorage:
    """Store application data in JSON files."""

    def __init__(self, data_directory: str | Path) -> None:
        self._data_directory = Path(data_directory).expanduser().resolve()

    def _read_json(self, filename: str, default: JSONData) -> JSONData:
        """Read JSON data and validate its structure."""
        file_path = self._data_directory / filename
        data = read_json_file(file_path, default)

        if not isinstance(data, type(default)):
            raise ValueError(f"Некорректная структура файла '{filename}'")

        return data

    def _write_json(self, filename: str, data: list | dict) -> None:
        """Write data to a JSON file."""
        file_path = self._data_directory / filename
        write_json_file(file_path, data)

    @staticmethod
    def _user_to_dict(user: User) -> dict:
        return {
            "user_id": user.user_id,
            "username": user.username,
            "hashed_password": user.hashed_password,
            "salt": user.salt,
            "registration_date": user.registration_date.isoformat(),
        }

    @staticmethod
    def _portfolio_to_dict(portfolio: Portfolio) -> dict:
        return {
            "user_id": portfolio.user_id,
            "wallets": {
                code: {"balance": wallet.balance}
                for code, wallet in portfolio.wallets.items()
            },
        }

    # CRUD User

    def add_user(self, user: User) -> None:
        """Add a user if their ID and username are unique."""
        users = self._read_json("users.json", [])
        if any(data["user_id"] == user.user_id for data in users):
            raise ValueError(f"Пользователь с ID {user.user_id} уже существует")
        if any(data["username"] == user.username for data in users):
            raise ValueError(f"Имя пользователя '{user.username}' уже занято")

        users.append(self._user_to_dict(user))
        self._write_json("users.json", users)

    def get_user(self, username: str) -> User | None:
        """Return a user by username, or None if absent."""
        users = self._read_json("users.json", [])

        for data in users:
            if data["username"] == username:
                return User(
                    user_id=data["user_id"],
                    username=data["username"],
                    hashed_password=data["hashed_password"],
                    salt=data["salt"],
                    registration_date=datetime.fromisoformat(data["registration_date"]),
                )

        return None

    def update_user(self, user: User) -> None:
        """Update an existing user by ID."""
        users = self._read_json("users.json", [])

        if any(
            data["username"] == user.username and data["user_id"] != user.user_id
            for data in users
        ):
            raise ValueError(f"Имя пользователя '{user.username}' уже занято")

        for index, data in enumerate(users):
            if data["user_id"] == user.user_id:
                if (
                    datetime.fromisoformat(data["registration_date"])
                    != user.registration_date
                ):
                    raise ValueError("Дата регистрации не может быть изменена!")
                users[index] = self._user_to_dict(user)
                break
        else:
            raise ValueError(f"Пользователь с ID {user.user_id} не найден")

        self._write_json("users.json", users)

    def delete_user(self, user_id: int) -> None:
        """Delete a user and their associated portfolios."""
        users = self._read_json("users.json", [])

        for index, data in enumerate(users):
            if data["user_id"] == user_id:
                portfolios = self._read_json("portfolios.json", [])

                portfolios = [
                    portfolio
                    for portfolio in portfolios
                    if portfolio["user_id"] != user_id
                ]

                self._write_json("portfolios.json", portfolios)

                users.pop(index)
                self._write_json("users.json", users)
                return

        raise ValueError(f"Пользователь с ID {user_id} не найден")

    # CRUD Portfolio

    def add_portfolio(self, portfolio: Portfolio) -> None:
        """Add a portfolio if the user has none."""
        portfolios = self._read_json("portfolios.json", [])
        if any(data["user_id"] == portfolio.user_id for data in portfolios):
            raise ValueError(
                f"Портфель пользователя {portfolio.user_id} уже существует"
            )

        portfolios.append(self._portfolio_to_dict(portfolio))
        self._write_json("portfolios.json", portfolios)

    def get_portfolio(self, user: User) -> Portfolio | None:
        """Return a user's portfolio, or None if absent."""
        portfolios = self._read_json("portfolios.json", [])

        for data in portfolios:
            if data["user_id"] == user.user_id:
                wallets = {
                    code: Wallet(code, wallet_data["balance"])
                    for code, wallet_data in data["wallets"].items()
                }
                return Portfolio(user, wallets)

        return None

    def update_portfolio(self, portfolio: Portfolio) -> None:
        """Update an existing portfolio by user ID."""
        portfolios = self._read_json("portfolios.json", [])
        for index, data in enumerate(portfolios):
            if data["user_id"] == portfolio.user_id:
                portfolios[index] = self._portfolio_to_dict(portfolio)
                self._write_json("portfolios.json", portfolios)
                return
        raise ValueError(f"Портфель пользователя {portfolio.user_id} не найден")

    def delete_portfolio(self, user_id: int) -> None:
        """Delete an existing portfolio by user ID."""
        portfolios = self._read_json("portfolios.json", [])
        for index, data in enumerate(portfolios):
            if data["user_id"] == user_id:
                portfolios.pop(index)
                self._write_json("portfolios.json", portfolios)
                return
        raise ValueError(f"Портфель пользователя {user_id} не найден")

    # INDEXES

    def get_next_user_id(self) -> int:
        """Return an ID greater than all existing user IDs."""
        users = self._read_json("users.json", [])
        return max((data["user_id"] for data in users), default=0) + 1

    # Rates cache

    def get_rates(self) -> dict:
        """Return the complete rates snapshot."""
        return self._read_json("rates.json", {})

    def update_rates(self, rates: dict) -> None:
        """Replace the complete rates snapshot."""
        self._write_json("rates.json", rates)


class DatabaseManager:
    """Manage the application storage using Singleton."""

    _instance: ClassVar[Self | None] = None
    _is_initialized: ClassVar[bool] = False

    def __new__(cls, storage: Storage | None = None) -> Self:
        if cls._instance is None:
            if storage is None:
                raise ValueError(
                    "При первой инициализации необходимо передать хранилище"
                )
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, storage: Storage | None = None) -> None:
        if type(self)._is_initialized:
            if storage is not None:
                raise RuntimeError(
                    "Хранилище можно передать только при первой инициализации"
                )
            return

        self._storage = storage
        type(self)._is_initialized = True

    @property
    def storage(self) -> Storage:
        """Return the configured storage."""
        return self._storage

    def add_user(self, user: User) -> None:
        self._storage.add_user(user)

    def get_user(self, username: str) -> User | None:
        return self._storage.get_user(username)

    def update_user(self, user: User) -> None:
        self._storage.update_user(user)

    def delete_user(self, user_id: int) -> None:
        self._storage.delete_user(user_id)

    def add_portfolio(self, portfolio: Portfolio) -> None:
        self._storage.add_portfolio(portfolio)

    def get_portfolio(self, user: User) -> Portfolio | None:
        return self._storage.get_portfolio(user)

    def update_portfolio(self, portfolio: Portfolio) -> None:
        self._storage.update_portfolio(portfolio)

    def delete_portfolio(self, user_id: int) -> None:
        self._storage.delete_portfolio(user_id)

    def get_next_user_id(self) -> int:
        return self._storage.get_next_user_id()

    def get_rates(self) -> dict:
        return self._storage.get_rates()

    def update_rates(self, rates: dict) -> None:
        self._storage.update_rates(rates)
