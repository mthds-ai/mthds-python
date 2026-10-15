from pathlib import Path

from mthds.method_tree.discovery import MANIFEST_NAME, find_manifest_directory, special_entry_kind
from mthds.method_tree.exceptions import TreeSourceError
from mthds.package.exceptions import ManifestReadError
from mthds.package.manifest.parser import parse_methods_toml
from mthds.package.manifest.schema import MethodsManifest

MANIFEST_FILENAME = MANIFEST_NAME


def find_package_manifest(bundle_path: Path) -> MethodsManifest | None:
    """Walk up from a bundle file's directory to find the nearest METHODS.toml, by Manifest Discovery.

    Each directory is checked for a regular file named exactly ``METHODS.toml`` first, letter case
    included whatever the file system; the walk then stops at a directory holding an entry named
    ``.git`` of any kind, a file or a symbolic link included, or at the file system's root.

    Args:
        bundle_path: Path to a .mthds bundle file

    Returns:
        The parsed MethodsManifest, or None if no manifest is found

    Raises:
        ManifestParseError: If a METHODS.toml is found but has invalid TOML syntax
        ManifestValidationError: If a METHODS.toml is found but fails validation
        ManifestReadError: If a directory on the way, or the manifest found, cannot be read
    """
    try:
        manifest_directory = find_manifest_directory(bundle_path.parent.resolve())
    except TreeSourceError as exc:
        msg = f"Cannot look for the {MANIFEST_FILENAME} of '{bundle_path}': {exc.message}"
        raise ManifestReadError(msg) from exc
    if manifest_directory is None:
        return None
    return _read_manifest_file(manifest_directory / MANIFEST_FILENAME)


def read_package_manifest_at(directory: Path) -> MethodsManifest | None:
    """Read the manifest of the package rooted at ``directory``, never looking above it.

    A package's root is known here, as for a dependency's checkout or cached copy, so only that
    directory is read: a manifest is a regular file named exactly ``METHODS.toml`` in it. A
    ``methods.toml`` is no manifest even on a case-insensitive file system, and the manifest of a
    package around this one is never taken for this one's.

    Returns:
        The parsed manifest, or None when the directory holds no entry named exactly ``METHODS.toml``.

    Raises:
        ManifestParseError: If the manifest has invalid TOML syntax
        ManifestValidationError: If the manifest fails validation
        ManifestReadError: If the directory or the manifest cannot be read, or ``METHODS.toml`` is
            not a regular file, such as a symbolic link
    """
    try:
        kind = special_entry_kind(directory, MANIFEST_FILENAME)
    except OSError as exc:
        msg = f"Cannot look for {MANIFEST_FILENAME} in '{directory}': {exc}"
        raise ManifestReadError(msg) from exc
    if kind is None:
        return None
    if not kind.is_regular_file:
        msg = f"The {MANIFEST_FILENAME} of '{directory}' is not a regular file, so it is no manifest; replace it with the file itself."
        raise ManifestReadError(msg)
    return _read_manifest_file(directory / MANIFEST_FILENAME)


def _read_manifest_file(manifest_path: Path) -> MethodsManifest:
    try:
        content = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"Cannot read '{manifest_path}': {exc}"
        raise ManifestReadError(msg) from exc
    return parse_methods_toml(content)
