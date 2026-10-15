"""Local package cache for fetched remote MTHDS dependencies.

Cache layout: ``{cache_root}/{CACHE_LAYOUT}/{address}/{version}/``
(e.g. ``~/.mthds/packages/v2/github.com/org/repo/1.0.0/``), each version directory holding the
package's method tree as written.

The layout is versioned because a cached copy is read back as written: a copy that an older
layout wrote is never read, since its files are not the package's tree. Copies written before
standard 7.0.0 sit at ``{cache_root}/{address}/{version}/`` and held the whole clone minus
``.git/``, its ``.gitignore`` files, ``__pycache__`` directories and symbolic links included;
this module never looks there, so such a package is fetched again, and the old copies can be
deleted.

Writes go through a hidden sibling directory renamed into place once complete.
"""

import secrets
import shutil
from pathlib import Path

from mthds.method_tree.exceptions import MethodTreeError
from mthds.method_tree.lister import list_method_tree_at_root
from mthds.method_tree.written_tree import write_tree
from mthds.package.exceptions import PackageCacheError

CACHE_LAYOUT = "v2"
"""The cache layout's version, the first directory under the cache root; bump it whenever what a cached copy holds changes."""


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
    layout_root = (cache_root or get_default_cache_root()).resolve() / CACHE_LAYOUT
    resolved = (layout_root / address / version).resolve()
    if not resolved.is_relative_to(layout_root):
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
    the rule excludes is left out. The tree is written into a hidden sibling directory and renamed
    into place once complete, and a copy already cached is moved aside and deleted first, so the
    version's directory only ever holds one whole tree.

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

    try:
        # A cached copy is replaced whole: the old one is moved aside under a hidden name, in one
        # rename, and only then deleted, so no reader ever sees a mix of the old tree and the new.
        if final_path.exists():
            retired_path = final_path.parent / f".{final_path.name}.{secrets.token_hex(8)}.retired"
            final_path.rename(retired_path)
            shutil.rmtree(retired_path)
        # `write_tree` writes into a hidden sibling and renames it into place once complete, so an
        # interrupted store leaves no copy under the version's name and `is_cached` stays false.
        write_tree(tree, destination=final_path)
    except OSError as exc:
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
