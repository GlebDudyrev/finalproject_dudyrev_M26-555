from valutatrade_hub.cli.interface import run_cli
from valutatrade_hub.infra.database import DatabaseManager, JsonStorage
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import configure_logging


def main() -> None:
    """Initialize application components and start the CLI."""
    settings = SettingsLoader()
    configure_logging(
        log_path=settings.get("log_path"),
        log_format=settings.get("log_format"),
    )

    storage = JsonStorage(
        data_directory=settings.get("data_dir"),
    )

    database_manager = DatabaseManager(storage)

    run_cli(
        database_manager,
        rates_ttl_seconds=settings.get("rates_ttl_seconds"),
        default_base_currency=settings.get("default_base_currency"),
    )


if __name__ == "__main__":
    main()
