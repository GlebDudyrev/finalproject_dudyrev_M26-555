from pathlib import Path
from typing import Protocol, TypeVar

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
