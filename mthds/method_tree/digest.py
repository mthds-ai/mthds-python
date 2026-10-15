r"""The tree digest: one hash naming a whole tree, whatever form its files traveled in.

The digest is `sha256:` followed by the SHA-256 of the tree's listing, which is one line per file,
ordered byte for byte on the tree paths' UTF-8 encoding, each line the file's SHA-256 in lowercase
hexadecimal, two spaces, its tree path and a line feed: exactly what
`printf '%s\n' … | LC_ALL=C sort | while IFS= read -r f; do sha256sum -- "$f"; done` prints
(`mthds/docs/spec/method-tree.md`, "The Tree Digest"). A tree path holds no backslash and no
line break, so no line is ever escaped.
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

from mthds.method_tree.models import TreeFile
from mthds.method_tree.tree_path import sorted_tree_paths, tree_path_sort_key

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

DIGEST_PREFIX = "sha256:"
SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TREE_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def sha256_hex(data: bytes) -> str:
    """The SHA-256 of `data` in lowercase hexadecimal."""
    return hashlib.sha256(data).hexdigest()


def tree_listing(files: Iterable[TreeFile]) -> bytes:
    """The tree's listing: one `<sha256>  <path>` line per file, in tree path order, each ended by a line feed."""
    ordered = sorted(files, key=lambda tree_file: tree_path_sort_key(tree_file.path))
    return b"".join(f"{tree_file.sha256}  {tree_file.path}\n".encode() for tree_file in ordered)


def tree_digest(files: Iterable[TreeFile]) -> str:
    """The tree digest, `sha256:` and the SHA-256 of the tree's listing."""
    return DIGEST_PREFIX + sha256_hex(tree_listing(files))


def tree_files_from_contents(contents: Mapping[str, bytes]) -> list[TreeFile]:
    """The files of a tree whose bytes are all at hand, keyed by tree path, in tree path order."""
    return [
        TreeFile(path=tree_path, sha256=sha256_hex(contents[tree_path]), size=len(contents[tree_path])) for tree_path in sorted_tree_paths(contents)
    ]


def digest_of_contents(contents: Mapping[str, bytes]) -> str:
    """The tree digest of a tree whose bytes are all at hand, keyed by tree path."""
    return tree_digest(tree_files_from_contents(contents))
