"""Listing a method tree from what a caller hands over: a directory, or a `.mthds` file named alone.

The procedure follows `mthds/docs/spec/method-tree.md`:

1. **Find the root.** Manifest Discovery walks up from the directory handed over, or from the
   directory of the file handed over, to the nearest directory holding `METHODS.toml`, stopping at
   a directory holding a `.git` entry of any kind. A directory with no manifest at or above it is
   its own root. A lone `.mthds` file with no manifest at or above it is a tree of that one file,
   and nothing beside it is read, not even a `.gitignore` file.
2. **Walk the root under the membership rule**, never following a symbolic link. Each entry is
   judged in this order: a name starting with a dot; for a directory, the name defaults
   (`__pycache__`, `node_modules`) and then the defaults read from its own entries (a `pyvenv.cfg`
   regular file or symbolic link, a `.git` entry of any kind, a regular `METHODS.toml` file); for
   any other entry, the run-inputs default (a regular file or symbolic link named exactly
   `inputs.json` or `inputs.toml`, at any depth); and last the patterns, the deepest `.gitignore`
   file first and the manifest's `[package] exclude` patterns below them all. An excluded
   directory is pruned, never visited, so nothing inside it is ever an error, its `.gitignore`
   file included. Only then is a kept entry refused when it is a symbolic link or another entry
   that is neither a regular file nor a directory, or when its path is not a tree path.
3. **Stop at the caller's limits while walking**, counting files and summing their sizes from
   `stat`, before any file is hashed.
4. **Refuse what the whole listing shows**: two spellings of one name equal in NFC, paths that
   collide once case-folded, a lone file the rule keeps out of its own tree, an empty tree.
5. **Hash every file** and compute the tree digest.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tomllib
from typing import TYPE_CHECKING, NamedTuple, cast

from mthds.method_tree.digest import tree_digest
from mthds.method_tree.discovery import (
    BUNDLE_SUFFIX,
    DEFAULT_DIRECTORY_NAMES,
    GITIGNORE_NAME,
    MANIFEST_NAME,
    RUN_INPUTS_NAMES,
    DirectoryEntry,
    EntryKind,
    find_manifest_directory,
    holds_git_entry,
    holds_manifest,
    holds_venv_marker,
    kind_of_exact_name,
    on_disk_name,
    read_directory,
)
from mthds.method_tree.exceptions import EmptyMethodTreeError, MethodTreeRefusedError, TreeLimitError, TreeRefusal, TreeSourceError
from mthds.method_tree.gitignore import PatternList
from mthds.method_tree.models import MethodTree, TreeExclusion, TreeFile, TreeLimits
from mthds.method_tree.tree_path import directories_of, nfc, refuse_path_collisions, sorted_tree_paths, tree_path_sort_key, tree_path_violation
from mthds.method_tree.vocabulary import ExclusionRule, TreeLimitKind, TreeRefusalCode

if TYPE_CHECKING:
    from pathlib import Path

HASH_CHUNK_BYTES = 1 << 20


class _Candidate(NamedTuple):
    """A regular file the walk kept: its tree path and its path as the file system spells it, both from the root."""

    tree_path: str
    raw_path: str


class _Frame(NamedTuple):
    """A directory the walk has still to visit."""

    tree_path: str
    raw_path: str
    entries: list[DirectoryEntry]
    pattern_lists: tuple[PatternList, ...]


def _join(prefix: str, name: str) -> str:
    return f"{prefix}/{name}" if prefix else name


def _name_sort_key(entry: DirectoryEntry) -> bytes:
    return tree_path_sort_key(nfc(entry.raw_name))


def list_method_tree(handed_over: Path, *, limits: TreeLimits | None = None) -> MethodTree:
    """List the method tree a caller hands over: a directory, or a `.mthds` file named alone.

    Args:
        handed_over: A directory, or a `.mthds` file. A symbolic link naming a directory is
            followed to it; a `.mthds` file named alone is never followed, so a link named so is
            refused as a symbolic link, as every link inside a tree is.
        limits: The limits to stop at while walking, before any file is hashed.

    Returns:
        The tree, its files in tree path order with their hashes and sizes, and its digest.

    Raises:
        EmptyMethodTreeError: When the membership rule keeps every file out of the tree; it carries what the listing
            kept out, so a caller learns the packages and repositories nested in a directory whose own tree is empty.
        MethodTreeRefusedError: When the standard refuses the tree; its `refusal.code` says why.
        TreeLimitError: When the walk passed one of `limits`.
        TreeSourceError: When `handed_over` does not exist, is a file not named `.mthds`, or when
            a directory, a file or the manifest cannot be read.
    """
    active_limits = limits or TreeLimits()
    try:
        status = os.lstat(handed_over)
        names_directory = stat.S_ISDIR(status.st_mode) or (stat.S_ISLNK(status.st_mode) and handed_over.is_dir())
        if names_directory:
            directory = handed_over.resolve(strict=True)
            root = find_manifest_directory(directory) or directory
            return _TreeWalk(root=root, limits=active_limits).list_tree(lone_file=None)
        parent = handed_over.absolute().parent.resolve(strict=True)
    except OSError as exc:
        msg = f"Cannot list a method tree from '{handed_over}': {exc}"
        raise TreeSourceError(msg) from exc
    # The file's name as its directory holds it: a case-insensitive file system also finds
    # `Main.mthds` for `main.mthds`, and the tree path must not follow the caller's spelling.
    lone_file = parent / on_disk_name(parent, handed_over.name)
    if not lone_file.name.endswith(BUNDLE_SUFFIX):
        msg = f"Cannot list a method tree from '{handed_over}': a file named alone must be a {BUNDLE_SUFFIX} bundle."
        raise TreeSourceError(msg)
    manifest_directory = find_manifest_directory(lone_file.parent)
    if manifest_directory is None:
        return _list_one_file_tree(lone_file, kind=_kind_of_status(status), limits=active_limits)
    return _TreeWalk(root=manifest_directory, limits=active_limits).list_tree(lone_file=lone_file)


def list_method_tree_at_root(root: Path, *, limits: TreeLimits | None = None) -> MethodTree:
    """List the tree rooted at `root` itself, with no Manifest Discovery, as a fetched package's tree is rooted at its directory.

    Raises:
        EmptyMethodTreeError: When the membership rule keeps every file out of the tree; it carries what the listing kept out.
        MethodTreeRefusedError: When the standard refuses the tree; its `refusal.code` says why.
        TreeLimitError: When the walk passed one of `limits`.
        TreeSourceError: When `root` is not a directory, or a directory, a file or the manifest cannot be read.
    """
    try:
        directory = root.resolve(strict=True)
    except OSError as exc:
        msg = f"Cannot list a method tree from '{root}': {exc}"
        raise TreeSourceError(msg) from exc
    if not directory.is_dir():
        msg = f"Cannot list a method tree rooted at '{root}': it is not a directory."
        raise TreeSourceError(msg)
    return _TreeWalk(root=directory, limits=limits or TreeLimits()).list_tree(lone_file=None)


def _kind_of_status(status: os.stat_result) -> EntryKind:
    if stat.S_ISLNK(status.st_mode):
        return EntryKind.SYMBOLIC_LINK
    if stat.S_ISDIR(status.st_mode):
        return EntryKind.DIRECTORY
    if stat.S_ISREG(status.st_mode):
        return EntryKind.FILE
    return EntryKind.SPECIAL


def _list_one_file_tree(lone_file: Path, *, kind: EntryKind, limits: TreeLimits) -> MethodTree:
    """The tree of one lone `.mthds` file with no manifest at or above it: that file alone, read under its own name.

    Nothing beside the file is read. Its name is judged as the one member of its tree: pruned
    first by the dot-segment rule, then refused when it is a symbolic link, never followed, or
    another entry that is not a regular file, or when it is not a tree path.
    """
    raw_name = lone_file.name
    tree_path = nfc(raw_name)
    root = lone_file.parent
    if tree_path.startswith("."):
        msg = (
            f"The bundle '{lone_file}' is kept out of its own method tree by {ExclusionRule.DOT_SEGMENT.description}; "
            "rename it so its name does not start with a dot."
        )
        refusal = TreeRefusal(code=TreeRefusalCode.LONE_FILE_EXCLUDED, names=[tree_path], excluded_by=ExclusionRule.DOT_SEGMENT)
        raise MethodTreeRefusedError(msg, refusal=refusal)
    _refuse_entry_kind(kind, tree_path=tree_path, root=root)
    _refuse_invalid_tree_path(tree_path, root=root)
    counter = _LimitCounter(root=root, limits=limits)
    counter.count_file(_stat_size(lone_file))
    tree_file = hash_file(lone_file, tree_path=tree_path)
    raw_paths = {tree_path: raw_name} if raw_name != tree_path else {}
    return MethodTree(
        files=[tree_file],
        digest=tree_digest([tree_file]),
        directory=root,
        is_one_file=True,
        entry=tree_path,
        raw_paths=raw_paths,
    )


class _LimitCounter:
    """Counts files and sums their sizes as the walk finds them, and stops at the first limit passed."""

    def __init__(self, *, root: Path, limits: TreeLimits) -> None:
        self.root = root
        self.limits = limits
        self.file_count = 0
        self.total_bytes = 0

    def count_file(self, size: int) -> None:
        self.file_count += 1
        self.total_bytes += size
        if self.limits.max_file_bytes is not None and size > self.limits.max_file_bytes:
            self._stop(kind=TreeLimitKind.FILE_BYTES, limit=self.limits.max_file_bytes, reached=size)
        if self.limits.max_files is not None and self.file_count > self.limits.max_files:
            self._stop(kind=TreeLimitKind.FILE_COUNT, limit=self.limits.max_files, reached=self.file_count)
        if self.limits.max_total_bytes is not None and self.total_bytes > self.limits.max_total_bytes:
            self._stop(kind=TreeLimitKind.TOTAL_BYTES, limit=self.limits.max_total_bytes, reached=self.total_bytes)

    def _stop(self, *, kind: TreeLimitKind, limit: int, reached: int) -> None:
        msg = (
            f"Stopped listing the method tree at '{self.root}' after reaching {reached} {kind.description}, "
            f"past the limit of {limit} {kind.description}. Check that this is the directory you meant to hand over."
        )
        raise TreeLimitError(msg, root=self.root, kind=kind, limit=limit, reached=reached)


class _TreeWalk:
    """One listing of a rooted tree."""

    def __init__(self, *, root: Path, limits: TreeLimits) -> None:
        self.root = root
        self.counter = _LimitCounter(root=root, limits=limits)
        self.candidates: list[_Candidate] = []
        self.spellings: dict[str, set[str]] = {}
        self.excluded_files: dict[str, TreeExclusion] = {}
        self.excluded_directories: dict[str, TreeExclusion] = {}
        self.raw_paths: dict[str, str] = {}
        self.manifest_patterns: PatternList | None = None

    def list_tree(self, *, lone_file: Path | None) -> MethodTree:
        root_entries = self._read_directory(tree_path="", raw_path="")
        root_exclusion: TreeExclusion | None = None
        if holds_venv_marker(root_entries):
            # The `pyvenv.cfg` default applies to the root too, so a root that is itself a virtual
            # environment holds an empty tree.
            root_exclusion = TreeExclusion(rule=ExclusionRule.VIRTUAL_ENVIRONMENT, directory=".")
        else:
            if holds_manifest(root_entries):
                self.manifest_patterns = self._read_manifest_patterns()
            self._walk(_Frame(tree_path="", raw_path="", entries=root_entries, pattern_lists=()))
        self._refuse_normalization_collisions()
        member_paths = [candidate.tree_path for candidate in self.candidates]
        refuse_path_collisions(member_paths, what=f"The method tree at '{self.root}'")
        entry: str | None = None
        if lone_file is not None:
            entry = self._lone_file_tree_path(lone_file)
            if entry not in member_paths:
                self._refuse_lone_file(lone_file, tree_path=entry, root_exclusion=root_exclusion)
        if not self.candidates:
            reason = (
                f"its root is {root_exclusion.rule.description}" if root_exclusion is not None else "the membership rule keeps every file out of it"
            )
            msg = f"The method tree at '{self.root}' is empty: {reason}, and a method tree holds at least one file."
            raise EmptyMethodTreeError(
                msg,
                root=self.root,
                excluded_files=self.excluded_files,
                excluded_directories=self.excluded_directories,
                raw_paths=self.raw_paths,
            )
        files = [self._hash(candidate) for candidate in sorted(self.candidates, key=lambda candidate: tree_path_sort_key(candidate.tree_path))]
        return MethodTree(
            files=files,
            digest=tree_digest(files),
            directory=self.root,
            entry=entry,
            excluded_files=self.excluded_files,
            excluded_directories=self.excluded_directories,
            raw_paths=self.raw_paths,
        )

    # ── Walking ─────────────────────────────────────────────────────────────

    def _walk(self, root_frame: _Frame) -> None:
        stack = [root_frame]
        while stack:
            frame = stack.pop()
            pattern_lists = self._with_gitignore(frame)
            children: list[_Frame] = []
            for directory_entry in sorted(frame.entries, key=_name_sort_key):
                name = nfc(directory_entry.raw_name)
                tree_path = _join(frame.tree_path, name)
                raw_path = _join(frame.raw_path, directory_entry.raw_name)
                child_entries: list[DirectoryEntry] = []
                exclusion: TreeExclusion | None
                if directory_entry.kind.is_directory:
                    exclusion, child_entries = self._judge_directory(name=name, tree_path=tree_path, raw_path=raw_path, pattern_lists=pattern_lists)
                else:
                    exclusion = self._judge_file(name, kind=directory_entry.kind) or self._judge_patterns(
                        tree_path, is_dir=False, pattern_lists=pattern_lists
                    )
                if exclusion is not None:
                    if directory_entry.kind.is_directory:
                        self.excluded_directories[tree_path] = exclusion
                    else:
                        self.excluded_files[tree_path] = exclusion
                    if raw_path != tree_path:
                        self.raw_paths[tree_path] = raw_path
                    continue
                self.spellings.setdefault(tree_path, set()).add(raw_path)
                if directory_entry.kind.is_directory:
                    children.append(_Frame(tree_path=tree_path, raw_path=raw_path, entries=child_entries, pattern_lists=pattern_lists))
                    continue
                self._keep_file(kind=directory_entry.kind, tree_path=tree_path, raw_path=raw_path)
            stack.extend(reversed(children))

    def _keep_file(self, *, kind: EntryKind, tree_path: str, raw_path: str) -> None:
        """Refuse a kept entry that is no regular file or whose path is no tree path, then count it."""
        _refuse_entry_kind(kind, tree_path=tree_path, root=self.root)
        _refuse_invalid_tree_path(tree_path, root=self.root)
        location = self._location(raw_path)
        self.counter.count_file(_stat_size(location))
        self.candidates.append(_Candidate(tree_path=tree_path, raw_path=raw_path))
        if raw_path != tree_path:
            self.raw_paths[tree_path] = raw_path

    # ── Judging an entry under the membership rule ─────────────────────────

    @staticmethod
    def _judge_name(name: str) -> TreeExclusion | None:
        if name.startswith("."):
            return TreeExclusion(rule=ExclusionRule.DOT_SEGMENT)
        return None

    @staticmethod
    def _judge_file(name: str, *, kind: EntryKind) -> TreeExclusion | None:
        """Judge an entry that is not a directory by its name, then by the run-inputs default; the patterns come after.

        A regular file or a symbolic link, never followed, named exactly `inputs.json` or
        `inputs.toml` is a run's inputs file and stays out wherever it lies; a named pipe or
        another special entry of either name is no run's inputs file, so it is kept and then
        refused as a special file.
        """
        by_name = _TreeWalk._judge_name(name)
        if by_name is not None:
            return by_name
        if name in RUN_INPUTS_NAMES and kind.counts_as_run_inputs:
            return TreeExclusion(rule=ExclusionRule.RUN_INPUTS)
        return None

    def _judge_directory(
        self,
        *,
        name: str,
        tree_path: str,
        raw_path: str,
        pattern_lists: tuple[PatternList, ...],
    ) -> tuple[TreeExclusion | None, list[DirectoryEntry]]:
        """Judge a directory by its name, then by its own entries, then by the patterns; returns its entries when it is kept."""
        by_name = self._judge_name(name)
        if by_name is not None:
            return by_name, []
        if name in DEFAULT_DIRECTORY_NAMES:
            return TreeExclusion(rule=ExclusionRule.PYCACHE_OR_NODE_MODULES), []
        try:
            entries = read_directory(self._location(raw_path))
        except OSError as exc:
            # A directory the patterns keep out need not be readable; any other one must be.
            by_pattern = self._judge_patterns(tree_path, is_dir=True, pattern_lists=pattern_lists)
            if by_pattern is not None:
                return by_pattern, []
            msg = f"Cannot list the directory {tree_path!r} of the method tree at '{self.root}': {exc}"
            raise TreeSourceError(msg) from exc
        if holds_venv_marker(entries):
            return TreeExclusion(rule=ExclusionRule.VIRTUAL_ENVIRONMENT, directory=tree_path), []
        if holds_git_entry(entries):
            return TreeExclusion(rule=ExclusionRule.NESTED_REPOSITORY, directory=tree_path), []
        if holds_manifest(entries):
            return TreeExclusion(rule=ExclusionRule.NESTED_PACKAGE, directory=tree_path), []
        return self._judge_patterns(tree_path, is_dir=True, pattern_lists=pattern_lists), entries

    def _judge_patterns(self, tree_path: str, *, is_dir: bool, pattern_lists: tuple[PatternList, ...]) -> TreeExclusion | None:
        """The patterns' verdict as git gives it: the deepest `.gitignore` file with a matching pattern decides, then the manifest's."""
        for pattern_list in reversed(pattern_lists):
            matched = pattern_list.last_match(tree_path, is_dir=is_dir)
            if matched is not None:
                return None if matched.negative else TreeExclusion(rule=ExclusionRule.GITIGNORE)
        if self.manifest_patterns is not None:
            matched = self.manifest_patterns.last_match(tree_path, is_dir=is_dir)
            if matched is not None and not matched.negative:
                return TreeExclusion(rule=ExclusionRule.PACKAGE_EXCLUDE)
        return None

    # ── Reading the pattern sources ─────────────────────────────────────────

    def _with_gitignore(self, frame: _Frame) -> tuple[PatternList, ...]:
        """The pattern lists that apply to a directory's entries: its parents', and its own `.gitignore` file's when it holds one."""
        kind = kind_of_exact_name(frame.entries, GITIGNORE_NAME)
        if kind is None or not kind.is_regular_file:
            # Git reads a `.gitignore` file only when it is a regular file; it never follows a link named so.
            return frame.pattern_lists
        gitignore_tree_path = _join(frame.tree_path, GITIGNORE_NAME)
        location = self._location(_join(frame.raw_path, GITIGNORE_NAME))
        try:
            data = location.read_bytes()
        except OSError as exc:
            msg = f"Cannot read {gitignore_tree_path!r} in the method tree at '{self.root}': {exc}"
            raise TreeSourceError(msg) from exc
        try:
            pattern_list = PatternList.make_from_bytes(data, base=frame.tree_path)
        except UnicodeDecodeError as exc:
            msg = (
                f"The file {gitignore_tree_path!r} in the method tree at '{self.root}' is not UTF-8, so its patterns cannot be read. "
                "Save it as UTF-8."
            )
            raise MethodTreeRefusedError(msg, refusal=TreeRefusal(code=TreeRefusalCode.GITIGNORE_NOT_UTF8, names=[gitignore_tree_path])) from exc
        return (*frame.pattern_lists, pattern_list)

    def _read_manifest_patterns(self) -> PatternList | None:
        """The root manifest's `[package] exclude` patterns, read as git reads `core.excludesFile`, or None when it has none."""
        manifest_location = self.root / MANIFEST_NAME
        try:
            manifest = tomllib.loads(manifest_location.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            msg = f"Cannot read the exclude patterns of '{manifest_location}': {exc}"
            raise TreeSourceError(msg) from exc
        package_section: object = manifest.get("package")
        if not isinstance(package_section, dict):
            return None
        exclude: object = cast("dict[str, object]", package_section).get("exclude")
        if exclude is None:
            return None
        if not isinstance(exclude, list):
            msg = f"The [package] exclude field of '{manifest_location}' must be an array of strings."
            raise TreeSourceError(msg)
        patterns: list[str] = []
        for pattern in cast("list[object]", exclude):
            if not isinstance(pattern, str):
                msg = f"The [package] exclude field of '{manifest_location}' must be an array of strings."
                raise TreeSourceError(msg)
            patterns.append(pattern)
        try:
            return PatternList.make_from_entries(patterns, base="")
        except ValueError as exc:
            msg = f"Cannot read the [package] exclude field of '{manifest_location}': {exc}"
            raise TreeSourceError(msg) from exc

    # ── Refusals judged on the whole listing ───────────────────────────────

    def _refuse_normalization_collisions(self) -> None:
        """Refuse two spellings, equal in NFC, of a name on the way to a kept file, naming each as the file system holds it."""
        colliding: set[str] = set()
        for candidate in self.candidates:
            for prefix in [*directories_of(candidate.tree_path), candidate.tree_path]:
                spellings = self.spellings.get(prefix, set())
                if len(spellings) > 1:
                    colliding |= spellings
        if colliding:
            names = sorted_tree_paths(colliding)
            shown = ", ".join(repr(name) for name in names)
            msg = (
                f"The method tree at '{self.root}' holds names equal once normalized to NFC: {shown}. "
                "A tree path is in NFC, so they would name one file; rename them apart."
            )
            raise MethodTreeRefusedError(msg, refusal=TreeRefusal(code=TreeRefusalCode.NORMALIZATION_COLLISION, names=names))

    def _lone_file_tree_path(self, lone_file: Path) -> str:
        """The lone file's tree path, each name on the way taken as the file system holds it, not as the caller spelled it."""
        current = self.root
        held_names: list[str] = []
        for part in lone_file.relative_to(self.root).parts:
            raw_name = on_disk_name(current, part)
            held_names.append(nfc(raw_name))
            current /= raw_name
        return "/".join(held_names)

    def _refuse_lone_file(self, lone_file: Path, *, tree_path: str, root_exclusion: TreeExclusion | None) -> None:
        exclusion = root_exclusion or self.excluded_files.get(tree_path)
        if exclusion is None:
            for directory in directories_of(tree_path):
                exclusion = self.excluded_directories.get(directory)
                if exclusion is not None:
                    break
        excluded_by = exclusion.rule if exclusion is not None else None
        excluded_directory = exclusion.directory if exclusion is not None and exclusion.rule.names_directory else None
        reason = f" by {excluded_by.description}" if excluded_by is not None else ""
        msg = (
            f"The bundle '{lone_file}' is kept out of the method tree rooted at '{self.root}'{reason}, so it cannot be listed as that tree's entry. "
            "Move it into the tree, or change the rule that keeps it out."
        )
        refusal = TreeRefusal(
            code=TreeRefusalCode.LONE_FILE_EXCLUDED,
            names=[tree_path],
            excluded_by=excluded_by,
            excluded_directory=excluded_directory,
        )
        raise MethodTreeRefusedError(msg, refusal=refusal)

    # ── Disk access ─────────────────────────────────────────────────────────

    def _location(self, raw_path: str) -> Path:
        return self.root.joinpath(*raw_path.split("/")) if raw_path else self.root

    def _read_directory(self, *, tree_path: str, raw_path: str) -> list[DirectoryEntry]:
        try:
            return read_directory(self._location(raw_path))
        except OSError as exc:
            shown = repr(tree_path) if tree_path else "root"
            msg = f"Cannot list the {shown} directory of the method tree at '{self.root}': {exc}"
            raise TreeSourceError(msg) from exc

    def _hash(self, candidate: _Candidate) -> TreeFile:
        return hash_file(self._location(candidate.raw_path), tree_path=candidate.tree_path)


def _refuse_entry_kind(kind: EntryKind, *, tree_path: str, root: Path) -> None:
    """Refuse a kept entry that is a symbolic link, or neither a regular file nor a directory."""
    match kind:
        case EntryKind.SYMBOLIC_LINK:
            msg = (
                f"The method tree at '{root}' holds a symbolic link, {tree_path!r}. A tree holds regular files only: "
                "replace the link with the file it names, or keep it out of the tree with a .gitignore pattern."
            )
            raise MethodTreeRefusedError(msg, refusal=TreeRefusal(code=TreeRefusalCode.SYMBOLIC_LINK, names=[tree_path]))
        case EntryKind.SPECIAL:
            msg = (
                f"The method tree at '{root}' holds {tree_path!r}, which is neither a regular file nor a directory. "
                "Remove it, or keep it out of the tree with a .gitignore pattern."
            )
            raise MethodTreeRefusedError(msg, refusal=TreeRefusal(code=TreeRefusalCode.SPECIAL_FILE, names=[tree_path]))
        case EntryKind.FILE | EntryKind.DIRECTORY:
            pass


def _refuse_invalid_tree_path(tree_path: str, *, root: Path) -> None:
    violation = tree_path_violation(tree_path)
    if violation is not None:
        msg = f"The method tree at '{root}' holds {tree_path!r}, which is not a tree path: {violation}. Rename it."
        raise MethodTreeRefusedError(msg, refusal=TreeRefusal(code=TreeRefusalCode.INVALID_TREE_PATH, names=[tree_path]))


def _stat_size(location: Path) -> int:
    try:
        return location.lstat().st_size
    except OSError as exc:
        msg = f"Cannot read the size of '{location}': {exc}"
        raise TreeSourceError(msg) from exc


def hash_file(location: Path, *, tree_path: str) -> TreeFile:
    """The file's hash and size, from the bytes read now."""
    hasher = hashlib.sha256()
    size = 0
    try:
        with location.open("rb") as stream:
            while chunk := stream.read(HASH_CHUNK_BYTES):
                hasher.update(chunk)
                size += len(chunk)
    except OSError as exc:
        msg = f"Cannot read '{location}': {exc}"
        raise TreeSourceError(msg) from exc
    return TreeFile(path=tree_path, sha256=hasher.hexdigest(), size=size)
