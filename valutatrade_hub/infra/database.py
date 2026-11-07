from pathlib import Path
from typing import ClassVar, Protocol, Self, TypeVar

from .utils import read_json_file, write_json_file

JSONData = TypeVar("JSONData", list, dict)


class Storage(Protocol):
    """Define the interface for persistent application storage."""
    ...


class JsonStorage:
    """Store application data in JSON files."""

    def __init__(self, data_directory: str | Path) -> None:
        self._data_directory = Path(data_directory).expanduser().resolve()

    def _read_json(
        self,
        filename: str,
        default: JSONData,
    ) -> JSONData:
        """Read JSON data and validate its structure."""
        file_path = self._data_directory / filename
        data = read_json_file(file_path, default)

        if not isinstance(data, type(default)):
            raise ValueError(f"Некорректная структура файла '{filename}'")

        return data

    def _write_json(
        self,
        filename: str,
        data: list | dict,
    ) -> None:
        """Write data to a JSON file."""
        file_path = self._data_directory / filename
        write_json_file(file_path, data)


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
