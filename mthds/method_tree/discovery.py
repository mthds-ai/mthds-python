"""Finding a method tree's root on disk, and reading a directory's entries by their exact names.

Every special name the standard gives (`METHODS.toml`, `.git`, `pyvenv.cfg`, `.gitignore`) is
matched exactly, letter case included, whatever the file system. On a case-insensitive file
system, asking whether `METHODS.toml` exists also answers for a file named `methods.toml`, so
this module never asks by name alone: it lists the directory and compares names.
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import TYPE_CHECKING, NamedTuple

from mthds.method_tree.exceptions import TreeSourceError
from mthds.method_tree.tree_path import nfc

if TYPE_CHECKING:
    from pathlib import Path

MANIFEST_NAME = "METHODS.toml"
GIT_ENTRY_NAME = ".git"
VENV_MARKER_NAME = "pyvenv.cfg"
GITIGNORE_NAME = ".gitignore"
DEFAULT_DIRECTORY_NAMES = frozenset({"__pycache__", "node_modules"})
BUNDLE_SUFFIX = ".mthds"


class EntryKind(StrEnum):
    """What a directory entry is, a symbolic link never followed."""

    FILE = "file"
    DIRECTORY = "directory"
    SYMBOLIC_LINK = "symbolic_link"
    SPECIAL = "special"

    @property
    def is_directory(self) -> bool:
        match self:
            case EntryKind.DIRECTORY:
                return True
            case EntryKind.FILE | EntryKind.SYMBOLIC_LINK | EntryKind.SPECIAL:
                return False

    @property
    def is_regular_file(self) -> bool:
        match self:
            case EntryKind.FILE:
                return True
            case EntryKind.DIRECTORY | EntryKind.SYMBOLIC_LINK | EntryKind.SPECIAL:
                return False

    @property
    def marks_virtual_environment(self) -> bool:
        """Whether a `pyvenv.cfg` entry of this kind marks its directory: a regular file or a symbolic link."""
        match self:
            case EntryKind.FILE | EntryKind.SYMBOLIC_LINK:
                return True
            case EntryKind.DIRECTORY | EntryKind.SPECIAL:
                return False


class DirectoryEntry(NamedTuple):
    """One entry of a directory: its name as the file system holds it, and its kind."""

    raw_name: str
    kind: EntryKind


def entry_kind(entry: os.DirEntry[str]) -> EntryKind:
    """The kind of a directory entry, never following a symbolic link."""
    if entry.is_symlink():
        return EntryKind.SYMBOLIC_LINK
    if entry.is_dir(follow_symlinks=False):
        return EntryKind.DIRECTORY
    if entry.is_file(follow_symlinks=False):
        return EntryKind.FILE
    return EntryKind.SPECIAL


def read_directory(directory: Path) -> list[DirectoryEntry]:
    """Every entry of a directory with its kind.

    Raises:
        OSError: When the directory cannot be listed.
    """
    with os.scandir(directory) as scanned:
        return [DirectoryEntry(raw_name=entry.name, kind=entry_kind(entry)) for entry in scanned]


def kind_of_exact_name(entries: list[DirectoryEntry], name: str) -> EntryKind | None:
    """The kind of the entry whose name is exactly `name`, or None when the directory holds none."""
    for entry in entries:
        if entry.raw_name == name:
            return entry.kind
    return None


def holds_manifest(entries: list[DirectoryEntry]) -> bool:
    """Whether a directory holds a regular file named exactly `METHODS.toml`."""
    kind = kind_of_exact_name(entries, MANIFEST_NAME)
    return kind is not None and kind.is_regular_file


def holds_git_entry(entries: list[DirectoryEntry]) -> bool:
    """Whether a directory holds an entry named exactly `.git`, of any kind, a file or a symbolic link included."""
    return kind_of_exact_name(entries, GIT_ENTRY_NAME) is not None


def holds_venv_marker(entries: list[DirectoryEntry]) -> bool:
    """Whether a directory holds a `pyvenv.cfg` that is a regular file or a symbolic link, the mark of a Python virtual environment."""
    kind = kind_of_exact_name(entries, VENV_MARKER_NAME)
    return kind is not None and kind.marks_virtual_environment


def find_manifest_directory(start: Path) -> Path | None:
    """Manifest Discovery: the nearest directory at or above `start` holding `METHODS.toml`, or None.

    Each directory is checked for a regular file named exactly `METHODS.toml` first; the walk then
    stops at a directory holding an entry named `.git` of any kind, or at the file system's root.

    Args:
        start: An existing directory, already resolved.

    Raises:
        TreeSourceError: When a directory on the way cannot be listed.
    """
    current = start
    while True:
        try:
            entries = read_directory(current)
        except OSError as exc:
            msg = f"Cannot look for {MANIFEST_NAME} in '{current}': {exc}"
            raise TreeSourceError(msg) from exc
        if holds_manifest(entries):
            return current
        if holds_git_entry(entries):
            return None
        parent = current.parent
        if parent == current:
            return None
        current = parent


def kind_at_tree_path(*, directory: Path, raw_directory: str, segments: list[str]) -> EntryKind | None:
    """The kind of the entry under `directory/raw_directory` whose names, in NFC, are `segments`, or None when there is none.

    A tree path is in NFC while the file system may hold a name in another form, so each level is
    listed and compared in NFC rather than looked up by name.
    """
    current = directory.joinpath(*raw_directory.split("/")) if raw_directory else directory
    kind = EntryKind.DIRECTORY
    for segment in segments:
        if not kind.is_directory:
            return None
        try:
            entries = read_directory(current)
        except OSError:
            return None
        found: DirectoryEntry | None = None
        for entry in entries:
            if nfc(entry.raw_name) == segment:
                found = entry
                break
        if found is None:
            return None
        kind = found.kind
        current /= found.raw_name
    return kind
