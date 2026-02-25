from typing import Any

import tomlkit
from pydantic import ValidationError

from mthds._utils.toml_utils import TomlError, load_toml_from_content
from mthds.package.exceptions import ManifestParseError, ManifestValidationError
from mthds.package.manifest.schema import MethodsManifest


def parse_methods_toml(content: str) -> MethodsManifest:
    """Parse METHODS.toml content into an MethodsManifest model.

    Args:
        content: The raw TOML string

    Returns:
        A validated MethodsManifest

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
        return MethodsManifest.model_validate(raw)
    except ValidationError as exc:
        msg = f"METHODS.toml validation failed: {exc}"
        raise ManifestValidationError(msg) from exc


def serialize_manifest_to_toml(manifest: MethodsManifest) -> str:
    """Serialize an MethodsManifest to a human-readable TOML string.

    Args:
        manifest: The manifest model to serialize

    Returns:
        A TOML-formatted string
    """
    doc = tomlkit.document()

    # [package] section
    package_table = tomlkit.table()
    if manifest.name is not None:
        package_table.add("name", manifest.name)
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
    if manifest.main_pipe is not None:
        package_table.add("main_pipe", manifest.main_pipe)
    doc.add("package", package_table)

    # [exports] section — build nested tables from dotted domain paths
    if manifest.exports:
        doc.add(tomlkit.nl())
        exports_table = tomlkit.table(is_super_table=True)

        for domain_path, domain_export in manifest.exports.items():
            segments = domain_path.split(".")
            # Navigate/create nested tables
            current: Any = exports_table
            for segment in segments:
                if segment not in current:
                    current.add(segment, tomlkit.table())
                current = current[segment]
            current.add("pipes", domain_export.pipes)

        doc.add("exports", exports_table)

    return tomlkit.dumps(doc)  # type: ignore[arg-type]
