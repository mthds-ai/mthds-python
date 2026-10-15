"""What a method tree is once listed or read: its files with their hashes and sizes, its digest, and where it came from."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from mthds.method_tree.vocabulary import ExclusionRule


class TreeFile(BaseModel):
    """One file of a tree: its tree path, the SHA-256 of its bytes in lowercase hexadecimal, and its size in bytes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    sha256: str
    size: int


class TreeExclusion(BaseModel):
    """The rule that kept an entry out of a tree listed from a directory, and for a nested repository or package, its directory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule: ExclusionRule
    directory: str | None = None


class TreeLimits(BaseModel):
    """The limits a caller lists a tree under; the listing stops at the first one passed, before hashing any file.

    The standard bounds a tree path's length and nothing else: a file's size, a tree's file count
    and its total size are each implementation's own policy (`mthds/docs/spec/method-tree.md`,
    "Limits"). A limit left as None is not checked.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_files: int | None = Field(default=None, ge=1)
    max_total_bytes: int | None = Field(default=None, ge=0)
    max_file_bytes: int | None = Field(default=None, ge=0)


class MethodTree(BaseModel):
    """A method tree: its files in tree path order, its digest, and what is known of where it came from.

    Attributes:
        files: The tree's files, ordered byte for byte on their tree paths' UTF-8 encoding.
        digest: `sha256:` and the tree digest, the SHA-256 of the tree's listing.
        directory: The directory the files are read from on disk: the root of a tree listed from a
            directory, the directory holding a lone file for its one-file tree, and None for a tree
            read from a map of file entries.
        is_one_file: Whether this is the one-file tree of a lone `.mthds` file named with no manifest
            at or above it, from which no reference reaches another file.
        entry: The tree path of the `.mthds` file a caller named alone, None when a directory was named.
        excluded_files: The entries a directory listing visited and kept out, by tree path, with the rule that kept each out.
        excluded_directories: The directories a directory listing pruned without visiting, by tree path, with the rule that pruned each.
        raw_paths: For a file or a pruned directory whose names the file system holds in another form than NFC, the
            path as the file system spells it, by tree path; a path spelled in NFC on disk is not listed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    files: list[TreeFile]
    digest: str
    directory: Path | None = None
    is_one_file: bool = False
    entry: str | None = None
    excluded_files: dict[str, TreeExclusion] = Field(default_factory=dict)
    excluded_directories: dict[str, TreeExclusion] = Field(default_factory=dict)
    raw_paths: dict[str, str] = Field(default_factory=dict)

    @property
    def tree_paths(self) -> list[str]:
        """The tree paths of the tree's files, in tree path order."""
        return [tree_file.path for tree_file in self.files]

    @cached_property
    def members(self) -> frozenset[str]:
        """The tree paths of the tree's files, as a set, built once: the model is frozen, so its files never change."""
        return frozenset(tree_file.path for tree_file in self.files)

    def file_location(self, tree_path: str) -> Path:
        """Where the file at `tree_path` lies on disk.

        Raises:
            ValueError: When the tree was not listed from a directory, or holds no file at `tree_path`.
        """
        if self.directory is None:
            msg = f"the tree was read from a map of file entries, so {tree_path!r} has no location on disk"
            raise ValueError(msg)
        if tree_path not in self.members:
            msg = f"the tree holds no file at {tree_path!r}"
            raise ValueError(msg)
        on_disk = self.raw_paths.get(tree_path, tree_path)
        return self.directory.joinpath(*on_disk.split("/"))
