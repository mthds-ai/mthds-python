from pathlib import Path

from mthds.method_tree.discovery import MANIFEST_NAME, find_manifest_directory
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
        TreeSourceError: If a directory on the way cannot be listed
    """
    manifest_directory = find_manifest_directory(bundle_path.parent.resolve())
    if manifest_directory is None:
        return None
    content = (manifest_directory / MANIFEST_FILENAME).read_text(encoding="utf-8")
    return parse_methods_toml(content)
