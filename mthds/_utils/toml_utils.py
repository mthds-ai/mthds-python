from __future__ import annotations

import os
import sys
from typing import Any

import tomlkit

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]


class TomlError(Exception):
    def __init__(self, message: str, doc: str, pos: int, lineno: int, colno: int):
        super().__init__(message)
        self.doc = doc
        self.pos = pos
        self.lineno = lineno
        self.colno = colno

    @classmethod
    def from_decode_error(cls, exc: Exception) -> TomlError:
        """Build from a tomllib/tomli TOMLDecodeError."""
        return cls(
            message=str(getattr(exc, "msg", str(exc))),
            doc=str(getattr(exc, "doc", "")),
            pos=int(getattr(exc, "pos", 0)),
            lineno=int(getattr(exc, "lineno", 0)),
            colno=int(getattr(exc, "colno", 0)),
        )


def load_toml_from_content(content: str) -> dict[str, Any]:
    """Load TOML from content string."""
    try:
        return tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        raise TomlError.from_decode_error(exc) from exc


def load_toml_from_path(path: str) -> dict[str, Any]:
    """Load TOML from file path.

    Args:
        path: Path to the TOML file

    Returns:
        Dictionary loaded from TOML

    Raises:
        TomlError: If TOML parsing fails, with file path included
    """
    try:
        with open(path, "rb") as file:
            return tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        msg = f"TOML parsing error in file '{path}': {getattr(exc, 'msg', str(exc))}"
        raise TomlError(
            message=msg,
            doc=str(getattr(exc, "doc", "")),
            pos=int(getattr(exc, "pos", 0)),
            lineno=int(getattr(exc, "lineno", 0)),
            colno=int(getattr(exc, "colno", 0)),
        ) from exc


def load_toml_from_path_if_exists(path: str) -> dict[str, Any] | None:
    """Load TOML from path if it exists."""
    if not os.path.exists(path):
        return None
    return load_toml_from_path(path)


def load_toml_with_tomlkit(path: str) -> tomlkit.TOMLDocument:
    """Load TOML using tomlkit to preserve formatting and comments.

    Args:
        path: Path to the TOML file

    Returns:
        TOMLDocument that preserves formatting and comments
    """
    with open(path, encoding="utf-8") as file:
        return tomlkit.load(file)


def save_toml_to_path(data: dict[str, Any] | tomlkit.TOMLDocument, path: str) -> None:
    """Save dictionary as TOML to path, preserving formatting and comments.

    Args:
        data: Dictionary or TOMLDocument to save as TOML
        path: Path where the TOML file should be saved
    """
    with open(path, "w", encoding="utf-8") as file:
        tomlkit.dump(data, file)  # type: ignore[arg-type]
