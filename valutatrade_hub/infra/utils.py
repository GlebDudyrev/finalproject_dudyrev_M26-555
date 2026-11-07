import json
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


def read_json_file(file_path: Path, default: T) -> T:
    """Read JSON data or return the default if the file does not exist."""
    try:
        with file_path.open(encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return default


def write_json_file(file_path: Path, data: object) -> None:
    """Serialize data and write it to a JSON file."""
    content = json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content + "\n", encoding="utf-8")
