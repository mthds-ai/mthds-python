from typing import Any

import tomlkit
from pydantic import ValidationError

from mthds._utils.toml_utils import TomlError, load_toml_from_content
from mthds.packages.exceptions import ManifestParseError, ManifestValidationError
from mthds.packages.manifest import MthdsPackageManifest


def parse_methods_toml(content: str) -> MthdsPackageManifest:
    """Parse METHODS.toml content into an MthdsPackageManifest model.

    Args:
        content: The raw TOML string

    Returns:
        A validated MthdsPackageManifest

    Raises:
        ManifestParseError: If the TOML syntax is invalid
        ManifestValidationError: If the parsed data fails model validation
    """
    try:
        raw = load_toml_from_content(content)
    except TomlError as exc:
        msg = f"Invalid TOML syntax in METHODS.toml: {exc}"
        raise ManifestParseError(msg) from exc

    try:
        return MthdsPackageManifest.model_validate(raw)
    except ValidationError as exc:
        msg = f"METHODS.toml validation failed: {exc}"
        raise ManifestValidationError(msg) from exc


def serialize_manifest_to_toml(manifest: MthdsPackageManifest) -> str:
    """Serialize an MthdsPackageManifest to a human-readable TOML string.

    Args:
        manifest: The manifest model to serialize

    Returns:
        A TOML-formatted string
    """
    doc = tomlkit.document()

    # [package] section
    package_table = tomlkit.table()
    package_table.add("address", manifest.address)
    if manifest.display_name is not None:
        package_table.add("display_name", manifest.display_name)
    package_table.add("version", manifest.version)
    package_table.add("description", manifest.description)
    if manifest.authors:
        package_table.add("authors", manifest.authors)
    if manifest.license is not None:
        package_table.add("license", manifest.license)
    if manifest.mthds_version is not None:
        package_table.add("mthds_version", manifest.mthds_version)
    doc.add("package", package_table)

    # [dependencies] section
    if manifest.dependencies:
        doc.add(tomlkit.nl())
        deps_table = tomlkit.table()
        for dep in manifest.dependencies:
            dep_table = tomlkit.inline_table()
            dep_table.append("address", dep.address)
            dep_table.append("version", dep.version)
            if dep.path is not None:
                dep_table.append("path", dep.path)
            deps_table.add(dep.alias, dep_table)
        doc.add("dependencies", deps_table)

    # [exports] section — build nested tables from dotted domain paths
    if manifest.exports:
        doc.add(tomlkit.nl())
        exports_table = tomlkit.table(is_super_table=True)

        for domain_export in manifest.exports:
            segments = domain_export.domain_path.split(".")
            # Navigate/create nested tables
            current: Any = exports_table
            for segment in segments:
                if segment not in current:
                    current.add(segment, tomlkit.table())
                current = current[segment]
            current.add("pipes", domain_export.pipes)

        doc.add("exports", exports_table)

    return tomlkit.dumps(doc)  # type: ignore[arg-type]
