from valutatrade_hub.cli.interface import run_cli
from valutatrade_hub.infra.database import DatabaseManager, JsonStorage
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import configure_logging
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.scheduler import RatesScheduler
from valutatrade_hub.parser_service.storage import ParserStorage
from valutatrade_hub.parser_service.updater import RatesUpdater


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

    parser_config = ParserConfig(data_dir=settings.get("data_dir"))
    rates_updater = RatesUpdater(
        clients={
            "CoinGecko": CoinGeckoClient(parser_config),
            "ExchangeRate-API": ExchangeRateApiClient(parser_config),
        },
        storage=ParserStorage(parser_config),
    )

    scheduler = RatesScheduler(
        rates_updater.run_update,
        interval_seconds=settings.get("parser_update_interval_seconds"),
    )
    if settings.get("parser_scheduler_enabled"):
        scheduler.start()

    try:
        run_cli(
            database_manager,
            rates_ttl_seconds=settings.get("rates_ttl_seconds"),
            default_base_currency=settings.get("default_base_currency"),
            refresh_rates=scheduler.run_update,
            update_rates=scheduler.run_update,
        )
    finally:
        if settings.get("parser_scheduler_enabled"):
            scheduler.stop()


if __name__ == "__main__":
    main()
