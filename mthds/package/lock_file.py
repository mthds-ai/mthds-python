"""Lock file model, digest computation, TOML I/O, generation, and verification.

The lock file (``methods.lock``) records, for each remote dependency, the exact resolved version
and the tree digest of the package's tree (``mthds/docs/spec/lock-format.md``), enabling
reproducible installs. A lock written before standard 7.0.0 records a ``hash`` instead, computed
by an algorithm that concatenated paths and contents with no separator; such a lock is refused at
parse, and its ``hash`` is never verified.
"""

from pathlib import Path
from typing import Any, cast

import tomlkit
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from mthds._utils.toml_utils import TomlError, load_toml_from_content
from mthds.method_tree.digest import DIGEST_PREFIX, TREE_DIGEST_PATTERN
from mthds.method_tree.exceptions import MethodTreeError
from mthds.method_tree.written_tree import written_tree_digest
from mthds.package.exceptions import IntegrityError, LockFileError
from mthds.package.manifest.schema import is_valid_semver
from mthds.package.package_cache import get_cached_package_path

LOCK_FILENAME = "methods.lock"
LEGACY_HASH_FIELD = "hash"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class LockedPackage(BaseModel):
    """A single locked dependency entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    digest: str
    source: str

    @field_validator("version")
    @classmethod
    def validate_version(cls, version: str) -> str:
        if not is_valid_semver(version):
            msg = f"Invalid version '{version}' in lock file. Must be valid semver."
            raise ValueError(msg)
        return version

    @field_validator("digest")
    @classmethod
    def validate_digest(cls, digest: str) -> str:
        if not TREE_DIGEST_PATTERN.match(digest):
            msg = f"Invalid digest '{digest}'. Must be '{DIGEST_PREFIX}' followed by exactly 64 lowercase hex characters."
            raise ValueError(msg)
        return digest

    @field_validator("source")
    @classmethod
    def validate_source(cls, source: str) -> str:
        if not source.startswith("https://"):
            msg = f"Invalid source '{source}'. Must start with 'https://'."
            raise ValueError(msg)
        return source


class LockFile(BaseModel):
    """The methods.lock file model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    packages: dict[str, LockedPackage] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Digest computation
# ---------------------------------------------------------------------------


def compute_package_digest(directory: Path) -> str:
    """Compute the tree digest of a package's tree written out to disk, such as its cached copy.

    Every regular file of the copy is a file of the tree at its path, and the membership rule is
    not applied again (``mthds/docs/spec/lock-format.md``, "Verification").

    Args:
        directory: The directory holding the written tree.

    Returns:
        ``sha256:`` followed by the tree digest.

    Raises:
        LockFileError: If the directory does not exist or does not hold a valid written tree.
    """
    if not directory.is_dir():
        msg = f"Directory '{directory}' does not exist or is not a directory"
        raise LockFileError(msg)
    try:
        return written_tree_digest(directory)
    except MethodTreeError as exc:
        msg = f"Cannot compute the tree digest of '{directory}': {exc.message}"
        raise LockFileError(msg) from exc


# ---------------------------------------------------------------------------
# TOML parse / serialize
# ---------------------------------------------------------------------------


def parse_lock_file(content: str) -> LockFile:
    """Parse a lock file TOML string into a ``LockFile`` model.

    Args:
        content: The raw TOML string.

    Returns:
        A validated ``LockFile``.

    Raises:
        LockFileError: If parsing or validation fails.
    """
    if not content.strip():
        return LockFile()

    try:
        raw = load_toml_from_content(content)
    except TomlError as exc:
        msg = f"Invalid TOML syntax in lock file: {exc}"
        raise LockFileError(msg) from exc

    packages: dict[str, LockedPackage] = {}
    for address, entry in raw.items():
        if not isinstance(entry, dict):
            msg = f"Lock file entry for '{address}' must be a table, got {type(entry).__name__}"
            raise LockFileError(msg)
        entry_dict = cast("dict[str, Any]", entry)
        if LEGACY_HASH_FIELD in entry_dict:
            msg = (
                f"The lock file entry for '{address}' records a `hash`, so this lock predates tree digests (MTHDS standard 7.0.0) "
                "and cannot be verified. Run `lock` to regenerate it."
            )
            raise LockFileError(msg)
        try:
            packages[str(address)] = LockedPackage(**entry_dict)
        except ValidationError as exc:
            msg = f"Invalid lock file entry for '{address}': {exc}"
            raise LockFileError(msg) from exc

    return LockFile(packages=packages)


def serialize_lock_file(lock_file: LockFile) -> str:
    """Serialize a ``LockFile`` to a TOML string.

    Entries are sorted by address for deterministic output (clean VCS diffs).

    Args:
        lock_file: The lock file model to serialize.

    Returns:
        A TOML-formatted string.
    """
    doc = tomlkit.document()

    for address in sorted(lock_file.packages):
        locked = lock_file.packages[address]
        table = tomlkit.table()
        table.add("version", locked.version)
        table.add("digest", locked.digest)
        table.add("source", locked.source)
        doc.add(address, table)

    return tomlkit.dumps(doc)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Lock file generation
# ---------------------------------------------------------------------------


def generate_lock_file(
    resolved_deps: list[Any],
) -> LockFile:
    """Generate a lock file from resolved dependencies.

    Locks all remote dependencies (including transitive) by using
    ``resolved.address`` directly. The caller is responsible for
    passing only remote dependencies (excluding local path overrides).

    Args:
        resolved_deps: List of ``ResolvedDependency`` from the resolver.

    Returns:
        A ``LockFile`` with entries for remote dependencies only.

    Raises:
        LockFileError: If a remote dependency has no manifest.
    """
    packages: dict[str, LockedPackage] = {}

    for resolved in resolved_deps:
        # Remote dep must have a manifest
        if resolved.manifest is None:
            msg = f"Remote dependency '{resolved.alias}' ({resolved.address}) has no manifest — cannot generate lock entry"
            raise LockFileError(msg)

        address = resolved.address
        version = resolved.manifest.version
        digest = compute_package_digest(resolved.package_root)
        source = f"https://{address}"

        packages[address] = LockedPackage(
            version=version,
            digest=digest,
            source=source,
        )

    return LockFile(packages=packages)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_locked_package(
    locked: LockedPackage,
    address: str,
    cache_root: Path | None = None,
) -> None:
    """Verify a single locked package against its cached copy.

    Args:
        locked: The locked package entry.
        address: The package address.
        cache_root: Override for the cache root directory.

    Raises:
        IntegrityError: If the cached package is missing or its tree digest does not match.
    """
    # Extract version to locate cached dir
    cached_path = get_cached_package_path(address, locked.version, cache_root)

    if not cached_path.is_dir():
        msg = f"Cached package '{address}@{locked.version}' not found at '{cached_path}'"
        raise IntegrityError(msg)

    try:
        actual_digest = compute_package_digest(cached_path)
    except LockFileError as exc:
        msg = f"Integrity check failed for '{address}@{locked.version}': {exc.message}"
        raise IntegrityError(msg) from exc
    if actual_digest != locked.digest:
        msg = f"Integrity check failed for '{address}@{locked.version}': expected the tree digest {locked.digest}, got {actual_digest}"
        raise IntegrityError(msg)


def verify_lock_file(
    lock_file: LockFile,
    cache_root: Path | None = None,
) -> None:
    """Verify all entries in a lock file against the cache.

    Args:
        lock_file: The lock file to verify.
        cache_root: Override for the cache root directory.

    Raises:
        IntegrityError: If any cached package is missing or its tree digest does not match.
    """
    for address, locked in lock_file.packages.items():
        verify_locked_package(locked, address, cache_root)
