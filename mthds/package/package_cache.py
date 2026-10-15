"""Local package cache for fetched remote MTHDS dependencies.

Cache layout: ``{cache_root}/{address}/{version}/``
(e.g. ``~/.mthds/packages/github.com/org/repo/1.0.0/``).

Uses a staging directory + atomic rename for safe writes.
"""

import shutil
from pathlib import Path

from mthds.method_tree.exceptions import MethodTreeError
from mthds.method_tree.lister import list_method_tree_at_root
from mthds.method_tree.written_tree import write_tree
from mthds.package.exceptions import PackageCacheError


def get_default_cache_root() -> Path:
    """Return the default cache root directory.

    Returns:
        ``~/.mthds/packages``
    """
    return Path.home() / ".mthds" / "packages"


def get_cached_package_path(
    address: str,
    version: str,
    cache_root: Path | None = None,
) -> Path:
    """Compute the cache path for a package version.

    Args:
        address: Package address, e.g. ``github.com/org/repo``.
        version: Resolved version string, e.g. ``1.0.0``.
        cache_root: Override for the cache root directory.

    Returns:
        The directory path where this package version would be cached.

    Raises:
        PackageCacheError: If the resolved path escapes the cache root (path traversal).
    """
    root = (cache_root or get_default_cache_root()).resolve()
    resolved = (root / address / version).resolve()
    if not resolved.is_relative_to(root):
        msg = f"Path traversal detected: address '{address}' and version '{version}' resolve outside cache root"
        raise PackageCacheError(msg)
    return resolved


def is_cached(
    address: str,
    version: str,
    cache_root: Path | None = None,
) -> bool:
    """Check whether a package version exists in the cache.

    A directory is considered cached if it exists and is non-empty.

    Args:
        address: Package address.
        version: Resolved version string.
        cache_root: Override for the cache root directory.

    Returns:
        True if the cached directory exists and is non-empty.
    """
    pkg_path = get_cached_package_path(address, version, cache_root)
    if not pkg_path.is_dir():
        return False
    return any(pkg_path.iterdir())


def store_in_cache(
    source_dir: Path,
    address: str,
    version: str,
    cache_root: Path | None = None,
) -> Path:
    """Write a fetched package's method tree into the cache.

    The tree is listed from ``source_dir`` under the membership rule, rooted at that directory,
    and only its files are written, each at its tree path: the cached copy is the tree as written,
    which a later digest reads back without applying the rule again. ``.git/`` and everything else
    the rule excludes is left out. Uses a staging directory (``{path}.staging``) and an atomic
    rename for safe writes.

    Args:
        source_dir: The directory to copy from (e.g. a fresh clone).
        address: Package address.
        version: Resolved version string.
        cache_root: Override for the cache root directory.

    Returns:
        The final cache path.

    Raises:
        PackageCacheError: If the package's tree is refused, or copying or renaming fails.
    """
    try:
        tree = list_method_tree_at_root(source_dir)
    except MethodTreeError as exc:
        msg = f"Failed to store package '{address}@{version}' in cache: {exc.message}"
        raise PackageCacheError(msg) from exc
    final_path = get_cached_package_path(address, version, cache_root)
    staging_path = final_path.parent / f"{final_path.name}.staging"

    try:
        # Clean up any leftover staging dir
        if staging_path.exists():
            shutil.rmtree(staging_path)

        # Write the package's tree into staging, each file at its tree path
        staging_path.mkdir(parents=True)
        write_tree(tree, destination=staging_path)

        # Ensure parent exists and perform atomic rename
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if final_path.exists():
            shutil.rmtree(final_path)
        staging_path.rename(final_path)

    except OSError as exc:
        # Clean up staging on failure
        if staging_path.exists():
            shutil.rmtree(staging_path, ignore_errors=True)
        msg = f"Failed to store package '{address}@{version}' in cache: {exc}"
        raise PackageCacheError(msg) from exc

    return final_path


def remove_cached_package(
    address: str,
    version: str,
    cache_root: Path | None = None,
) -> bool:
    """Remove a cached package version.

    Args:
        address: Package address.
        version: Resolved version string.
        cache_root: Override for the cache root directory.

    Returns:
        True if the directory existed and was removed, False otherwise.
    """
    pkg_path = get_cached_package_path(address, version, cache_root)
    if not pkg_path.exists():
        return False
    try:
        shutil.rmtree(pkg_path)
    except OSError as exc:
        msg = f"Failed to remove cached package '{address}@{version}' at '{pkg_path}': {exc}"
        raise PackageCacheError(msg) from exc
    return True
