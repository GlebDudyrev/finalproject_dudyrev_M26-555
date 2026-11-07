from datetime import UTC, datetime

from valutatrade_hub.core.models import Portfolio, User
from valutatrade_hub.core.utils import generate_salt, hash_password
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
