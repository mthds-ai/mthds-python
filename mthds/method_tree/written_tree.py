"""A tree written out to disk, and read back as written.

A copy of a tree that a program writes, such as a package in a cache, holds the tree's files at
their tree paths and nothing else, and those files are the tree: a reader takes every file of the
copy as a file of the tree and never applies the membership rule again
(`mthds/docs/spec/method-tree.md`, "A tree written out is read back as written"). The rule could
not be applied twice anyway, since the `.gitignore` files that shaped the tree start with a dot and
are left out of the copy.
"""

from __future__ import annotations

import secrets
import shutil
from typing import TYPE_CHECKING

from mthds.method_tree.digest import tree_digest
from mthds.method_tree.discovery import EntryKind, read_directory
from mthds.method_tree.exceptions import MethodTreeRefusedError, TreeRefusal, TreeSourceError
from mthds.method_tree.lister import hash_file
from mthds.method_tree.models import MethodTree, TreeFile
from mthds.method_tree.tree_path import directories_of, nfc, refuse_path_collisions, sorted_tree_paths, tree_path_sort_key, tree_path_violation
from mthds.method_tree.vocabulary import TreeRefusalCode

if TYPE_CHECKING:
    from pathlib import Path


def write_tree(tree: MethodTree, *, destination: Path) -> None:
    """Write the files of a tree listed from a directory as the directory `destination`, each at its tree path, and nothing else.

    The files are written into a fresh hidden directory beside `destination`, which takes the name
    `destination` only once every file is written: an interrupted write never leaves a partial tree
    under that name, and what it leaves beside it starts with a dot. `destination` must not exist,
    or be an empty directory. A directory already holding files is refused rather than replaced or
    written into: files of both trees would mix, and replacing it would delete what a caller may
    not mean to lose, so a caller replacing a tree it owns, such as the package cache, removes the
    old one first.

    Each file keeps its permission bits, so a script the package marks executable stays so; the
    digest does not cover them.

    Raises:
        ValueError: When the tree was not listed from a directory.
        FileExistsError: When `destination` exists and is not an empty directory.
        OSError: When a file cannot be read or written.
    """
    _refuse_occupied_destination(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.{secrets.token_hex(8)}.writing"
    staging.mkdir()
    is_in_place = False
    try:
        for tree_file in tree.files:
            target = staging.joinpath(*tree_file.path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tree.file_location(tree_file.path)
            shutil.copyfile(source, target)
            shutil.copymode(source, target)
        if destination.is_dir():
            # `rmdir` removes only an empty directory, so a file written there meanwhile is never lost.
            destination.rmdir()
        staging.rename(destination)
        is_in_place = True
    finally:
        if not is_in_place:
            shutil.rmtree(staging, ignore_errors=True)


def _refuse_occupied_destination(destination: Path) -> None:
    if not destination.exists() and not destination.is_symlink():
        return
    if destination.is_dir() and not destination.is_symlink() and not any(destination.iterdir()):
        return
    msg = (
        f"Cannot write a method tree at '{destination}': it already exists and is not an empty directory, "
        "and a written tree holds nothing but its files."
    )
    raise FileExistsError(msg)


def read_written_tree(directory: Path) -> MethodTree:
    """Read back a tree written out: every regular file under `directory` is a file of the tree, at its path.

    Raises:
        MethodTreeRefusedError: When the copy holds a symbolic link, another entry that is neither a
            regular file nor a directory, a path that is not a tree path, two spellings of one name
            equal in NFC, or paths that collide.
        TreeSourceError: When the directory, or a file of it, cannot be read.
    """
    found: list[tuple[str, str]] = []
    spellings: dict[str, set[str]] = {}
    pending: list[tuple[str, str]] = [("", "")]
    while pending:
        tree_prefix, raw_prefix = pending.pop()
        location = directory.joinpath(*raw_prefix.split("/")) if raw_prefix else directory
        try:
            entries = read_directory(location)
        except OSError as exc:
            msg = f"Cannot list '{location}': {exc}"
            raise TreeSourceError(msg) from exc
        for entry in entries:
            tree_path = f"{tree_prefix}/{nfc(entry.raw_name)}" if tree_prefix else nfc(entry.raw_name)
            raw_path = f"{raw_prefix}/{entry.raw_name}" if raw_prefix else entry.raw_name
            spellings.setdefault(tree_path, set()).add(raw_path)
            match entry.kind:
                case EntryKind.DIRECTORY:
                    pending.append((tree_path, raw_path))
                case EntryKind.FILE:
                    found.append((tree_path, raw_path))
                case EntryKind.SYMBOLIC_LINK:
                    msg = f"The tree written at '{directory}' holds a symbolic link, {tree_path!r}; a written tree holds regular files only."
                    raise MethodTreeRefusedError(msg, refusal=TreeRefusal(code=TreeRefusalCode.SYMBOLIC_LINK, names=[tree_path]))
                case EntryKind.SPECIAL:
                    msg = f"The tree written at '{directory}' holds {tree_path!r}, which is neither a regular file nor a directory."
                    raise MethodTreeRefusedError(msg, refusal=TreeRefusal(code=TreeRefusalCode.SPECIAL_FILE, names=[tree_path]))
    for tree_path, _raw_path in found:
        violation = tree_path_violation(tree_path)
        if violation is not None:
            msg = f"The tree written at '{directory}' holds {tree_path!r}, which is not a tree path: {violation}."
            raise MethodTreeRefusedError(msg, refusal=TreeRefusal(code=TreeRefusalCode.INVALID_TREE_PATH, names=[tree_path]))
    _refuse_normalization_collisions(directory, found=found, spellings=spellings)
    refuse_path_collisions([tree_path for tree_path, _raw_path in found], what=f"The tree written at '{directory}'")
    if not found:
        msg = f"The tree written at '{directory}' holds no file, and a method tree holds at least one."
        raise MethodTreeRefusedError(msg, refusal=TreeRefusal(code=TreeRefusalCode.EMPTY_TREE))
    found.sort(key=lambda pair: tree_path_sort_key(pair[0]))
    files: list[TreeFile] = [hash_file(directory.joinpath(*raw_path.split("/")), tree_path=tree_path) for tree_path, raw_path in found]
    raw_paths = {tree_path: raw_path for tree_path, raw_path in found if tree_path != raw_path}
    return MethodTree(files=files, digest=tree_digest(files), directory=directory, raw_paths=raw_paths)


def _refuse_normalization_collisions(directory: Path, *, found: list[tuple[str, str]], spellings: dict[str, set[str]]) -> None:
    """Refuse two spellings, equal in NFC, of a name on the way to a file, naming each as the file system holds it.

    Both would be read at one tree path, so one file would be lost; the lister refuses the same.
    """
    colliding: set[str] = set()
    for tree_path, _raw_path in found:
        for prefix in [*directories_of(tree_path), tree_path]:
            held_spellings = spellings.get(prefix, set())
            if len(held_spellings) > 1:
                colliding |= held_spellings
    if colliding:
        names = sorted_tree_paths(colliding)
        shown = ", ".join(repr(name) for name in names)
        msg = (
            f"The tree written at '{directory}' holds names equal once normalized to NFC: {shown}; "
            "a tree path is in NFC, so they would name one file."
        )
        raise MethodTreeRefusedError(msg, refusal=TreeRefusal(code=TreeRefusalCode.NORMALIZATION_COLLISION, names=names))


def written_tree_digest(directory: Path) -> str:
    """The tree digest of a tree written out, read back as written."""
    return read_written_tree(directory).digest
