"""Model and discovery for method package contents."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from mthds.package.discovery import MANIFEST_FILENAME, read_package_manifest_at
from mthds.package.exceptions import ManifestError
from mthds.package.manifest.schema import MethodsManifest


class MethodsPackage(BaseModel):
    """Contents of a method package: its manifest and all .mthds bundle files."""

    model_config = ConfigDict(extra="forbid")

    manifest: MethodsManifest
    mthds_files: list[str] = Field(default_factory=list, description="Relative paths to .mthds files from package root")


def make_package_from_directory(package_root: Path) -> MethodsPackage:
    """Discover the contents of a method package from its root directory.

    Parses the METHODS.toml manifest and recursively finds all .mthds bundle files,
    storing their paths relative to the package root.

    Args:
        package_root: Path to the package root directory (must contain METHODS.toml)

    Returns:
        A MethodsPackage with the parsed manifest and list of .mthds file paths

    Raises:
        ManifestError: If METHODS.toml is missing, unreadable, or invalid
    """
    # The manifest is a regular file named exactly METHODS.toml at the root, letter case included,
    # whatever the file system: `Path.is_file` would follow a link and match `methods.toml`.
    manifest = read_package_manifest_at(package_root)
    if manifest is None:
        msg = f"No {MANIFEST_FILENAME} found in {package_root}"
        raise ManifestError(msg)

    mthds_files = sorted(str(mthds_path.relative_to(package_root)) for mthds_path in package_root.rglob("*.mthds") if mthds_path.is_file())

    return MethodsPackage(
        manifest=manifest,
        mthds_files=mthds_files,
    )
