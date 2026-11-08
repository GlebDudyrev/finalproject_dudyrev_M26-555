import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, ClassVar, Self

from .utils import read_json_file

APP_NAME = "valutatrade_hub"


def _get_xdg_directory(
    env_variable: str,
    default_directory: Path,
) -> Path:
    """Return an XDG directory or its default location."""
    configured_directory = os.environ.get(env_variable)

    if configured_directory:
        directory = Path(configured_directory).expanduser()

        if directory.is_absolute():
            return directory

    return default_directory


def _get_default_data_dir() -> str:
    data_home = _get_xdg_directory(
        "XDG_DATA_HOME",
        Path.home() / ".local" / "share",
    )
    return str(data_home / APP_NAME / "data")


def _get_default_log_path() -> str:
    state_home = _get_xdg_directory(
        "XDG_STATE_HOME",
        Path.home() / ".local" / "state",
    )
    return str(state_home / APP_NAME / "logs" / "actions.log")


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Application configuration with validated values."""

    data_dir: str = field(default_factory=_get_default_data_dir)
    rates_ttl_seconds: int = 300
    parser_scheduler_enabled: bool = False
    parser_update_interval_seconds: int = 300
    default_base_currency: str = "USD"
    log_format: str = "text"
    log_path: str = field(default_factory=_get_default_log_path)

    def __post_init__(self) -> None:
        self._validate_settings()
        self._normalize_paths()

    def _validate_settings(self) -> None:
        if type(self.parser_scheduler_enabled) is not bool:
            raise ValueError("parser_scheduler_enabled должен быть булевым значением")
        if (
            type(self.parser_update_interval_seconds) is not int
            or self.parser_update_interval_seconds <= 0
        ):
            raise ValueError(
                "parser_update_interval_seconds должен быть положительным целым числом"
            )

        if type(self.rates_ttl_seconds) is not int or self.rates_ttl_seconds < 0:
            raise ValueError("Некорректное значение rates_ttl_seconds")

        currency = self.default_base_currency
        if (
            not isinstance(currency, str)
            or not 2 <= len(currency) <= 5
            or not currency.isalpha()
            or not currency.isupper()
        ):
            raise ValueError(f"Некорректное значение default_base_currency: {currency}")

        if self.log_format not in ("text", "json"):
            raise ValueError(
                f"log_format должен быть 'text' или 'json' передан: {self.log_format}"
            )

        for name in ("data_dir", "log_path"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Некорректное значение настройки '{name}'")

    def _normalize_paths(self) -> None:
        for name in ("data_dir", "log_path"):
            path = Path(getattr(self, name)).expanduser().resolve()
            object.__setattr__(self, name, str(path))

    @classmethod
    def from_config(
        cls,
        config_values: dict[str, Any],
        config_directory: Path,
    ) -> Self:
        """Create settings from configuration file values."""
        supported_keys = {item.name for item in fields(cls)}
        unknown_keys = config_values.keys() - supported_keys

        if unknown_keys:
            raise ValueError(
                f"Неизвестные настройки: {', '.join(sorted(unknown_keys))}"
            )

        settings_values = config_values.copy()

        for name in ("data_dir", "log_path"):
            if name not in settings_values:
                continue

            value = settings_values[name]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Некорректное значение настройки '{name}'")

            path = Path(value).expanduser()
            if not path.is_absolute():
                path = config_directory / path

            settings_values[name] = str(path.resolve())

        return cls(**settings_values)


class SettingsLoader:
    """Load and cache application settings using Singleton."""

    _instance: ClassVar[Self | None] = None
    _is_initialized: ClassVar[bool] = False

    def __new__(cls, config_path: str | Path | None = None) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)

        return cls._instance

    def __init__(self, config_path: str | Path | None = None) -> None:
        if type(self)._is_initialized:
            if config_path is not None:
                raise RuntimeError(
                    "Путь к конфигурации можно передать только при первой инициализации"
                )
            return

        if config_path is None:
            config_directory = _get_xdg_directory(
                "XDG_CONFIG_HOME",
                Path.home() / ".config",
            )
            config_path = config_directory / APP_NAME / "config.json"

        self._config_path = Path(config_path).expanduser().resolve()
        self._settings = self._load_settings()
        type(self)._is_initialized = True

    def _load_settings(self) -> AppSettings:
        """Load application settings from the configuration file."""
        config_values = self._read_config_file()

        return AppSettings.from_config(
            config_values,
            self._config_path.parent,
        )

    def _read_config_file(self) -> dict[str, Any]:
        """Read configuration values from JSON."""
        config_values = read_json_file(self._config_path, {})

        if not isinstance(config_values, dict):
            raise ValueError("Конфигурация должна быть объектом JSON")

        return config_values

    def get(self, key: str, default: Any = None) -> Any:
        """Return a configuration value or the provided fallback."""
        supported_keys = {item.name for item in fields(AppSettings)}

        if key not in supported_keys:
            return default

        return getattr(self._settings, key)

    def reload(self) -> None:
        """Reload application settings from the configuration file."""
        self._settings = self._load_settings()
