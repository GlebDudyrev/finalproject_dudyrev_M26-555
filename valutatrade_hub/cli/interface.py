import argparse
import shlex
from typing import NoReturn

from valutatrade_hub.core.models import User
from valutatrade_hub.core.usecases import UseCaseError, login, register
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


def execute_command(
    command: str,
    arguments: list[str],
    parser: CommandParser,
    storage: Storage,
    current_user: User | None,
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

        case "show-portfolio" | "buy" | "sell" | "get-rate":
            parser.parse_args([command, *arguments])
            print(f"Команда '{command}' пока не реализована.")

        case "exit":
            parser.parse_args([command, *arguments])
            return False, current_user

        case _:
            print(f"Неизвестная команда '{command}'.")

    return True, current_user



def run_cli(storage: Storage) -> None:
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
            )
        except InvalidCommandArguments:
            print(f"Некорректные аргументы команды '{command}'.")
            continue
        except UseCaseError as error:
            print(error)
            continue

        if not should_continue:
            break
