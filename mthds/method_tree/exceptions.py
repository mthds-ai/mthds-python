"""The errors of the method tree.

A refusal the standard defines is a `MethodTreeRefusedError` carrying a `TreeRefusal`, whose
`code` is the stable contract a consumer branches on; the message is presentation. A listing
that stops at a caller's limit is a `TreeLimitError`, and a source that cannot be listed at all,
such as a path that does not exist, is a `TreeSourceError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from mthds.method_tree.vocabulary import ExclusionRule, TreeLimitKind, TreeRefusalCode

if TYPE_CHECKING:
    from pathlib import Path


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
