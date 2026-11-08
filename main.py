from valutatrade_hub.cli.interface import run_cli
from valutatrade_hub.infra.database import DatabaseManager, JsonStorage
from valutatrade_hub.infra.settings import SettingsLoader


def main() -> None:
    """Initialize application components and start the CLI."""
    settings = SettingsLoader()

    storage = JsonStorage(
        data_directory=settings.get("data_dir"),
    )

    database_manager = DatabaseManager(storage)

    run_cli(
        database_manager,
        rates_ttl_seconds=settings.get("rates_ttl_seconds"),
    )


if __name__ == "__main__":
    main()
