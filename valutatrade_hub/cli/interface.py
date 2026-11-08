import argparse
import shlex
from collections.abc import Callable
from typing import NoReturn

from valutatrade_hub.core.currencies import (
    CryptoCurrency,
    get_currency,
    get_supported_currency_codes,
)
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
    RatesCacheError,
)
from valutatrade_hub.core.models import User
from valutatrade_hub.core.usecases import (
    RatesRefresh,
    UseCaseError,
    buy,
    get_rate,
    login,
    register,
    sell,
    show_portfolio,
    show_rates,
)
from valutatrade_hub.infra.database import Storage
from valutatrade_hub.parser_service.updater import UpdateResult

SOURCE_NAMES = {"coingecko": "CoinGecko", "exchangerate": "ExchangeRate-API"}
RatesUpdate = Callable[[str | None], UpdateResult]


class InvalidCommandArguments(Exception):
    """Indicate invalid arguments of a CLI command."""


class CommandParser(argparse.ArgumentParser):
    """Parse arguments without terminating the application."""

    def error(self, message: str) -> NoReturn:
        raise InvalidCommandArguments(message)


def _add_auth_arguments(parser: argparse.ArgumentParser) -> None:
    """Add authentication arguments."""
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)


def _add_trade_arguments(parser: argparse.ArgumentParser) -> None:
    """Add trading arguments."""
    parser.add_argument("--currency", required=True)
    parser.add_argument("--amount", required=True, type=float)


def _add_portfolio_arguments(
    parser: argparse.ArgumentParser, default_base_currency: str
) -> None:
    """Add portfolio arguments."""
    parser.add_argument("--base", default=default_base_currency)


def _add_rate_arguments(parser: argparse.ArgumentParser) -> None:
    """Add exchange-rate arguments."""
    parser.add_argument("--from", dest="from_code", required=True)
    parser.add_argument("--to", dest="to_code", required=True)


def _positive_int(value: str) -> int:
    """Parse a strictly positive count for the --top option."""
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Ожидается положительное целое число"
        ) from error
    if number <= 0:
        raise argparse.ArgumentTypeError("Ожидается положительное целое число")
    return number


def create_command_parser(default_base_currency: str = "USD") -> CommandParser:
    """Create the application command parser."""
    parser = CommandParser(
        prog="valutatrade",
        add_help=False,
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=CommandParser,
    )

    for name in ("register", "login"):
        command_parser = commands.add_parser(
            name,
            add_help=False,
            allow_abbrev=False,
        )
        _add_auth_arguments(command_parser)

    for name in ("buy", "sell"):
        command_parser = commands.add_parser(
            name,
            add_help=False,
            allow_abbrev=False,
        )
        _add_trade_arguments(command_parser)

    portfolio_parser = commands.add_parser(
        "show-portfolio",
        add_help=False,
        allow_abbrev=False,
    )
    _add_portfolio_arguments(portfolio_parser, default_base_currency)

    rate_parser = commands.add_parser(
        "get-rate",
        add_help=False,
        allow_abbrev=False,
    )
    _add_rate_arguments(rate_parser)

    update_parser = commands.add_parser(
        "update-rates",
        add_help=False,
        allow_abbrev=False,
    )
    update_parser.add_argument("--source", choices=tuple(SOURCE_NAMES))

    show_rates_parser = commands.add_parser(
        "show-rates",
        add_help=False,
        allow_abbrev=False,
    )
    show_rates_parser.add_argument("--currency")
    show_rates_parser.add_argument("--top", type=_positive_int)
    show_rates_parser.add_argument("--base", default=default_base_currency)

    commands.add_parser(
        "exit",
        add_help=False,
        allow_abbrev=False,
    )
    return parser


def _format_rate(rate: float) -> str:
    """Format exchange rates without insignificant trailing zeros."""
    return f"{rate:.8f}".rstrip("0").rstrip(".")


def execute_command(
    command: str,
    arguments: list[str],
    parser: CommandParser,
    storage: Storage,
    current_user: User | None,
    rates_ttl_seconds: int = 300,
    refresh_rates: RatesRefresh | None = None,
    update_rates: RatesUpdate | None = None,
) -> tuple[bool, User | None]:
    """Execute a command and return the updated CLI state."""
    match command:
        case "register":
            args = parser.parse_args([command, *arguments])
            user = register(args.username, args.password, storage)
            print(
                f"Пользователь '{user.username}' зарегистрирован (id={user.user_id})."
            )

        case "login":
            args = parser.parse_args([command, *arguments])
            current_user = login(args.username, args.password, storage)
            print(f"Вы вошли как '{current_user.username}'")

        case "get-rate":
            args = parser.parse_args([command, *arguments])
            rate, updated_at = get_rate(
                args.from_code,
                args.to_code,
                storage,
                ttl_seconds=rates_ttl_seconds,
                refresh_rates=refresh_rates,
            )
            print(
                f"Курс {args.from_code}→{args.to_code}: {_format_rate(rate)} "
                f"(обновлено: {updated_at:%Y-%m-%d %H:%M:%S})"
            )
            print(
                f"Обратный курс {args.to_code}→{args.from_code}: "
                f"{_format_rate(1 / rate)}"
            )

        case "update-rates":
            args = parser.parse_args([command, *arguments])
            if update_rates is None:
                raise UseCaseError("Сервис обновления курсов не настроен")
            source = SOURCE_NAMES[args.source] if args.source is not None else None
            result = update_rates(source)
            if result.errors:
                print("Обновление завершено с ошибками:")
                for provider, reason in result.errors.items():
                    print(f"- {provider}: {reason}")
            else:
                print("Обновление курсов завершено успешно.")
            print(f"Получено котировок: {result.fetched}; обновлено: {result.updated}.")
            print(f"Добавлено измерений в историю: {result.history_added}.")
            if result.last_refresh is not None:
                print(f"Последнее обновление: {result.last_refresh}")

        case "show-rates":
            args = parser.parse_args([command, *arguments])
            rows, last_refresh = show_rates(
                storage,
                currency_code=args.currency,
                top=args.top,
                base_currency=args.base,
            )
            print(f"Rates from cache (updated at {last_refresh or 'не указано'}):")
            for pair, rate, updated_at in rows:
                print(f"- {pair}: {_format_rate(rate)} (обновлено: {updated_at})")

        case "show-portfolio":
            args = parser.parse_args([command, *arguments])
            wallet_values, total = show_portfolio(
                current_user,
                storage,
                base_currency=args.base,
                ttl_seconds=rates_ttl_seconds,
                refresh_rates=refresh_rates,
            )
            print(
                f"Портфель пользователя '{current_user.username}' (база: {args.base}):"
            )
            if not wallet_values:
                print("В портфеле нет кошельков.")
            else:
                for code, balance, value in wallet_values:
                    digits = 4 if isinstance(get_currency(code), CryptoCurrency) else 2
                    print(f"- {code}: {balance:.{digits}f}  → {value:.2f} {args.base}")
                print("---------------------------------")
                print(f"ИТОГО: {total:,.2f} {args.base}")

        case "buy":
            args = parser.parse_args([command, *arguments])
            previous, current, rate = buy(
                current_user,
                args.currency,
                args.amount,
                storage,
                rates_ttl_seconds,
                refresh_rates=refresh_rates,
            )
            digits = 4 if isinstance(get_currency(args.currency), CryptoCurrency) else 2
            formatted_rate = f"{rate:.2f}" if rate >= 1 else _format_rate(rate)
            print(
                f"Покупка выполнена: {args.amount:.{digits}f} {args.currency} "
                f"по курсу {formatted_rate} USD/{args.currency}"
            )
            print("Изменения в портфеле:")
            print(
                f"- {args.currency}: было {previous:.{digits}f} "
                f"→ стало {current:.{digits}f}"
            )
            print(f"Оценочная стоимость покупки: {args.amount * rate:,.2f} USD")

        case "sell":
            args = parser.parse_args([command, *arguments])
            previous, current, rate = sell(
                current_user,
                args.currency,
                args.amount,
                storage,
                rates_ttl_seconds,
                refresh_rates=refresh_rates,
            )
            digits = 4 if isinstance(get_currency(args.currency), CryptoCurrency) else 2
            formatted_rate = f"{rate:.2f}" if rate >= 1 else _format_rate(rate)
            print(
                f"Продажа выполнена: {args.amount:.{digits}f} {args.currency} "
                f"по курсу {formatted_rate} USD/{args.currency}"
            )
            print("Изменения в портфеле:")
            print(
                f"- {args.currency}: было {previous:.{digits}f} "
                f"→ стало {current:.{digits}f}"
            )
            print(f"Оценочная выручка: {args.amount * rate:,.2f} USD")

        case "exit":
            parser.parse_args([command, *arguments])
            return False, current_user

        case _:
            print(f"Неизвестная команда '{command}'.")

    return True, current_user


def run_cli(
    storage: Storage,
    rates_ttl_seconds: int = 300,
    default_base_currency: str = "USD",
    refresh_rates: RatesRefresh | None = None,
    update_rates: RatesUpdate | None = None,
) -> None:
    """Run the interactive command-line interface."""
    parser = create_command_parser(default_base_currency)

    current_user: User | None = None

    print("ValutaTrade Hub")
    print("Для завершения работы введите exit.")

    while True:
        try:
            command_line = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        try:
            arguments = shlex.split(command_line)
        except ValueError:
            print("Некорректный ввод: проверьте кавычки.")
            continue

        if not arguments:
            continue

        command, *command_arguments = arguments

        try:
            should_continue, current_user = execute_command(
                command,
                command_arguments,
                parser,
                storage,
                current_user,
                rates_ttl_seconds,
                refresh_rates,
                update_rates,
            )
        except InvalidCommandArguments:
            print(f"Некорректные аргументы команды '{command}'.")
            continue
        except CurrencyNotFoundError as error:
            print(error)
            print("Поддерживаемые валюты: " + ", ".join(get_supported_currency_codes()))
            continue
        except ApiRequestError as error:
            print(error)
            print("Повторите попытку позже или проверьте сеть.")
            continue
        except RatesCacheError as error:
            print(error)
            print(
                "Сохраните повреждённый rates.json как резервную копию, "
                "удалите исходный файл и выполните update-rates."
            )
            continue
        except (UseCaseError, InsufficientFundsError) as error:
            print(error)
            continue

        if not should_continue:
            break
