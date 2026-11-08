import argparse
import shlex
from typing import NoReturn

from valutatrade_hub.core.currencies import CryptoCurrency, get_currency
from valutatrade_hub.core.exceptions import ApiRequestError, CurrencyNotFoundError
from valutatrade_hub.core.models import User
from valutatrade_hub.core.usecases import (
    UseCaseError,
    get_rate,
    login,
    register,
    show_portfolio,
)
from valutatrade_hub.infra.database import Storage


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


def _add_portfolio_arguments(parser: argparse.ArgumentParser) -> None:
    """Add portfolio arguments."""
    parser.add_argument("--base", default="USD")


def _add_rate_arguments(parser: argparse.ArgumentParser) -> None:
    """Add exchange-rate arguments."""
    parser.add_argument("--from", dest="from_code", required=True)
    parser.add_argument("--to", dest="to_code", required=True)


def create_command_parser() -> CommandParser:
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
    _add_portfolio_arguments(portfolio_parser)

    rate_parser = commands.add_parser(
        "get-rate",
        add_help=False,
        allow_abbrev=False,
    )
    _add_rate_arguments(rate_parser)

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
            )
            print(
                f"Курс {args.from_code}→{args.to_code}: {_format_rate(rate)} "
                f"(обновлено: {updated_at:%Y-%m-%d %H:%M:%S})"
            )
            print(
                f"Обратный курс {args.to_code}→{args.from_code}: "
                f"{_format_rate(1 / rate)}"
            )

        case "show-portfolio":
            args = parser.parse_args([command, *arguments])
            wallet_values, total = show_portfolio(
                current_user,
                storage,
                base_currency=args.base,
                ttl_seconds=rates_ttl_seconds,
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

        case "buy" | "sell":
            parser.parse_args([command, *arguments])
            print(f"Команда '{command}' пока не реализована.")

        case "exit":
            parser.parse_args([command, *arguments])
            return False, current_user

        case _:
            print(f"Неизвестная команда '{command}'.")

    return True, current_user


def run_cli(storage: Storage, rates_ttl_seconds: int = 300) -> None:
    """Run the interactive command-line interface."""
    parser = create_command_parser()

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
            )
        except InvalidCommandArguments:
            print(f"Некорректные аргументы команды '{command}'.")
            continue
        except CurrencyNotFoundError as error:
            print(error)
            print("Проверьте код валюты: он должен быть в числе поддерживаемых.")
            continue
        except ApiRequestError as error:
            print(error)
            print("Повторите попытку позже или проверьте сеть.")
            continue
        except UseCaseError as error:
            print(error)
            continue

        if not should_continue:
            break
