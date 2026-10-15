"""Tree paths: what names a file of a method tree, how two of them collide, and how they sort.

A tree path is a relative POSIX path in Unicode NFC, with no empty, `.` or `..` segment, no
backslash, colon or control character (general category `Cc`) in a segment, at most 255 UTF-8
bytes per segment and 1024 for the whole path (`mthds/docs/spec/method-tree.md`, "Tree Paths").
A segment starting with a dot is still a tree path: the membership rule, not this one, keeps
`.env` out of every tree.

Two tree paths collide when their Unicode full case foldings are equal, the folding of a path
being `nfc(nfc(path).casefold())`: Python's `str.casefold` is the full case folding of
`CaseFolding.txt`, statuses C and F, with no locale tailoring, so `straße.txt` collides with
`STRASSE.txt`, and a name spelled with the long s (U+017F) with the same name spelled with `s`. A path also collides with a directory of another,
so `Templates` and `templates/letter.html` never share a tree.
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING

from mthds.method_tree.exceptions import MethodTreeRefusedError, TreeRefusal
from mthds.method_tree.vocabulary import TreeRefusalCode

if TYPE_CHECKING:
    from collections.abc import Iterable

MAX_SEGMENT_BYTES = 255
MAX_PATH_BYTES = 1024
CONTROL_CATEGORY = "Cc"


def nfc(text: str) -> str:
    """The text in Unicode Normalization Form C."""
    return unicodedata.normalize("NFC", text)


def holds_control_character(text: str) -> bool:
    """Whether the text holds a character of general category `Cc`, NUL and the line breaks among them."""
    return any(unicodedata.category(character) == CONTROL_CATEGORY for character in text)


def segment_violation(segment: str) -> str | None:
    """Why one segment cannot be part of a tree path, or None when it can; NFC and the path's length are the path's to check."""
    if not segment:
        return "it holds an empty segment"
    if segment in {".", ".."}:
        return f"it holds the segment {segment!r}"
    if "\\" in segment:
        return "it holds a backslash"
    if ":" in segment:
        return "it holds a colon"
    if holds_control_character(segment):
        return "it holds a control character"
    try:
        encoded = segment.encode("utf-8")
    except UnicodeEncodeError:
        return "it holds a code point UTF-8 cannot encode"
    if len(encoded) > MAX_SEGMENT_BYTES:
        return f"a segment is longer than {MAX_SEGMENT_BYTES} bytes"
    return None


def tree_path_violation(candidate: str) -> str | None:
    """Why `candidate` is not a tree path, or None when it is one.

    A candidate not already in NFC is not a tree path: a path given as text is never normalized.
    """
    if not candidate:
        return "it is empty"
    if candidate.startswith("/") or candidate.endswith("/"):
        return "it starts or ends with '/'"
    for segment in candidate.split("/"):
        violation = segment_violation(segment)
        if violation is not None:
            return violation
    if not unicodedata.is_normalized("NFC", candidate):
        return "it is not in Unicode Normalization Form C"
    if len(candidate.encode("utf-8")) > MAX_PATH_BYTES:
        return f"it is longer than {MAX_PATH_BYTES} bytes"
    return None


def is_tree_path(candidate: str) -> bool:
    """Whether `candidate` is a tree path."""
    return tree_path_violation(candidate) is None


def check_tree_path(candidate: str) -> str:
    """Return `candidate` when it is a tree path, and refuse it as `invalid_tree_path` naming it otherwise."""
    violation = tree_path_violation(candidate)
    if violation is not None:
        msg = f"{candidate!r} is not a tree path: {violation}."
        raise MethodTreeRefusedError(msg, refusal=TreeRefusal(code=TreeRefusalCode.INVALID_TREE_PATH, names=[candidate]))
    return candidate


def tree_path_sort_key(tree_path: str) -> bytes:
    """The key ordering tree paths byte for byte on their UTF-8 encoding, as `LC_ALL=C sort` orders them."""
    return tree_path.encode("utf-8", errors="surrogatepass")


def sorted_tree_paths(tree_paths: Iterable[str]) -> list[str]:
    """The paths ordered byte for byte on their UTF-8 encoding."""
    return sorted(tree_paths, key=tree_path_sort_key)


def case_fold(tree_path: str) -> str:
    """The key two tree paths collide on: the full case folding of the path in NFC, normalized to NFC again."""
    return nfc(nfc(tree_path).casefold())


def directories_of(tree_path: str) -> list[str]:
    """The directories a tree path names, outermost first: `a/b/c` names `a` and `a/b`."""
    segments = tree_path.split("/")
    return ["/".join(segments[:depth]) for depth in range(1, len(segments))]


def path_collisions(tree_paths: Iterable[str]) -> list[str]:
    """Every path equal to another once both are case-folded, or naming a directory of another, sorted byte for byte.

    The empty list means no two of the paths collide.
    """
    paths = list(tree_paths)
    by_folded: dict[str, set[str]] = {}
    for tree_path in paths:
        by_folded.setdefault(case_fold(tree_path), set()).add(tree_path)
    under_folded_directory: dict[str, set[str]] = {}
    for tree_path in paths:
        for directory in directories_of(tree_path):
            under_folded_directory.setdefault(case_fold(directory), set()).add(tree_path)
    colliding: set[str] = set()
    for group in by_folded.values():
        if len(group) > 1:
            colliding |= group
    for tree_path in paths:
        under = under_folded_directory.get(case_fold(tree_path))
        if under:
            colliding.add(tree_path)
            colliding |= under
    return sorted_tree_paths(colliding)


def refuse_path_collisions(tree_paths: Iterable[str], *, what: str) -> None:
    """Refuse as `path_collision`, naming every colliding path, a set of paths two of which collide."""
    colliding = path_collisions(tree_paths)
    if colliding:
        shown = ", ".join(repr(path) for path in colliding)
        msg = (
            f"{what} holds paths that collide once case-folded, or a path naming a directory of another: {shown}. "
            "A tree written out on a case-insensitive file system would lose one of them; rename them apart."
        )
        raise MethodTreeRefusedError(msg, refusal=TreeRefusal(code=TreeRefusalCode.PATH_COLLISION, names=colliding))
