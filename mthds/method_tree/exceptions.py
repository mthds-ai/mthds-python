"""The errors of the method tree.

A refusal the standard defines is a `MethodTreeRefusedError` carrying a `TreeRefusal`, whose
`code` is the stable contract a consumer branches on; the message is presentation. A tree listed
from a directory and refused as empty is an `EmptyMethodTreeError`, which also carries what the
listing kept out. A listing that stops at a caller's limit is a `TreeLimitError`, and a source that
cannot be listed at all, such as a path that does not exist, is a `TreeSourceError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from mthds.method_tree.vocabulary import ExclusionRule, TreeLimitKind, TreeRefusalCode

if TYPE_CHECKING:
    from pathlib import Path

    from mthds.method_tree.models import TreeExclusion


class TreeRefusal(BaseModel):
    """A refusal as the conformance corpus records it: its code, what it names, and for a reference where it resolved."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: TreeRefusalCode
    names: list[str] = Field(default_factory=list)
    resolved: str | None = None
    excluded_by: ExclusionRule | None = None
    excluded_directory: str | None = None


class MethodTreeError(Exception):
    """Base error of the method tree."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class MethodTreeRefusedError(MethodTreeError):
    """A tree, a map of file entries, a tree path, a file reference or a function name the standard refuses."""

    def __init__(self, message: str, *, refusal: TreeRefusal) -> None:
        self.refusal = refusal
        super().__init__(message)


class EmptyMethodTreeError(MethodTreeRefusedError):
    """A tree listed from a directory that the membership rule leaves empty, with what the listing kept out of it.

    The refusal is the corpus's `empty_tree`, naming nothing, and the exclusions ride on the error rather than on an
    empty `MethodTree` or on the `TreeRefusal` record, since the standard holds that a tree has at least one file and
    the corpus pins this refusal's record as its code alone. A caller that lists a directory to find the packages and
    repositories nested in it, such as a runtime reading a library directory, reads them from `excluded_directories`
    whether or not the directory's own tree holds a file.

    Attributes:
        root: The root of the listing, which the tree paths below are relative to.
        excluded_files: The entries the listing visited and kept out, by tree path, with the rule that kept each out.
        excluded_directories: The directories the listing pruned without visiting, by tree path, with the rule that
            pruned each; a nested package or repository names its own directory.
        raw_paths: For an excluded entry whose names the file system holds in another form than NFC, the path as the
            file system spells it, by tree path.
    """

    def __init__(
        self,
        message: str,
        *,
        root: Path,
        excluded_files: dict[str, TreeExclusion],
        excluded_directories: dict[str, TreeExclusion],
        raw_paths: dict[str, str],
    ) -> None:
        self.root = root
        self.excluded_files = excluded_files
        self.excluded_directories = excluded_directories
        self.raw_paths = raw_paths
        super().__init__(message, refusal=TreeRefusal(code=TreeRefusalCode.EMPTY_TREE))


class TreeLimitError(MethodTreeError):
    """A listing that stopped at one of the limits its caller gave, before hashing any file."""

    def __init__(self, message: str, *, root: Path, kind: TreeLimitKind, limit: int, reached: int) -> None:
        self.root = root
        self.kind = kind
        self.limit = limit
        self.reached = reached
        super().__init__(message)


class TreeSourceError(MethodTreeError):
    """What a caller handed over cannot be listed: a missing path, an unreadable file or a malformed manifest."""
