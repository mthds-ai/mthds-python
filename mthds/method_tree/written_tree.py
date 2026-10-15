"""A tree written out to disk, and read back as written.

A copy of a tree that a program writes, such as a package in a cache, holds the tree's files at
their tree paths and nothing else, and those files are the tree: a reader takes every file of the
copy as a file of the tree and never applies the membership rule again
(`mthds/docs/spec/method-tree.md`, "A tree written out is read back as written"). The rule could
not be applied twice anyway, since the `.gitignore` files that shaped the tree start with a dot and
are left out of the copy.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from mthds.method_tree.digest import tree_digest
from mthds.method_tree.discovery import EntryKind, read_directory
from mthds.method_tree.exceptions import MethodTreeRefusedError, TreeRefusal, TreeSourceError
from mthds.method_tree.lister import hash_file
from mthds.method_tree.models import MethodTree, TreeFile
from mthds.method_tree.tree_path import nfc, refuse_path_collisions, tree_path_sort_key, tree_path_violation
from mthds.method_tree.vocabulary import TreeRefusalCode

if TYPE_CHECKING:
    from pathlib import Path


def write_tree(tree: MethodTree, *, destination: Path) -> None:
    """Copy the files of a tree listed from a directory to `destination`, each at its tree path, and nothing else.

    Raises:
        ValueError: When the tree was not listed from a directory.
        OSError: When a file cannot be read or written.
    """
    for tree_file in tree.files:
        target = destination.joinpath(*tree_file.path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tree.file_location(tree_file.path), target)


def read_written_tree(directory: Path) -> MethodTree:
    """Read back a tree written out: every regular file under `directory` is a file of the tree, at its path.

    Raises:
        MethodTreeRefusedError: When the copy holds a symbolic link, another entry that is neither a
            regular file nor a directory, a path that is not a tree path, or paths that collide.
        TreeSourceError: When the directory, or a file of it, cannot be read.
    """
    found: list[tuple[str, str]] = []
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
    refuse_path_collisions([tree_path for tree_path, _raw_path in found], what=f"The tree written at '{directory}'")
    if not found:
        msg = f"The tree written at '{directory}' holds no file, and a method tree holds at least one."
        raise MethodTreeRefusedError(msg, refusal=TreeRefusal(code=TreeRefusalCode.EMPTY_TREE))
    found.sort(key=lambda pair: tree_path_sort_key(pair[0]))
    files: list[TreeFile] = [hash_file(directory.joinpath(*raw_path.split("/")), tree_path=tree_path) for tree_path, raw_path in found]
    raw_paths = {tree_path: raw_path for tree_path, raw_path in found if tree_path != raw_path}
    return MethodTree(files=files, digest=tree_digest(files), directory=directory, raw_paths=raw_paths)


def written_tree_digest(directory: Path) -> str:
    """The tree digest of a tree written out, read back as written."""
    return read_written_tree(directory).digest
