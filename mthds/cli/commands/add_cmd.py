import re
from pathlib import Path

import typer
from pydantic import ValidationError
from rich.markup import escape

from mthds.cli._console import get_console
from mthds.packages.discovery import MANIFEST_FILENAME
from mthds.packages.exceptions import ManifestError
from mthds.packages.manifest import PackageDependency
from mthds.packages.manifest_parser import parse_methods_toml, serialize_manifest_to_toml


def derive_alias_from_address(address: str) -> str:
    """Derive a snake_case alias from a package address.

    Takes the last path segment and converts hyphens/dots to underscores.

    Args:
        address: The package address (e.g. "github.com/org/my-package")

    Returns:
        A snake_case alias (e.g. "my_package")
    """
    last_segment = address.rstrip("/").rsplit("/", maxsplit=1)[-1]
    # Replace hyphens and dots with underscores, lowercase
    alias = re.sub(r"[-.]", "_", last_segment).lower()
    # Remove any non-alphanumeric/underscore characters
    alias = re.sub(r"[^a-z0-9_]", "", alias)
    # Remove leading/trailing underscores
    alias = alias.strip("_")
    return alias or "dep"


def do_add(
    address: str,
    alias: str | None = None,
    version: str = "0.1.0",
    path: str | None = None,
    directory: Path | None = None,
) -> None:
    """Add a dependency to METHODS.toml.

    Args:
        address: The package address (e.g. "github.com/org/repo")
        alias: The dependency alias (auto-derived from address if not provided)
        version: The version constraint
        path: Optional local filesystem path
        directory: Package directory (defaults to current directory)
    """
    console = get_console()
    cwd = Path(directory).resolve() if directory else Path.cwd()
    manifest_path = cwd / MANIFEST_FILENAME

    # Check that METHODS.toml exists
    if not manifest_path.exists():
        console.print(f"[red]{MANIFEST_FILENAME} not found in {escape(str(cwd))}.[/red]")
        console.print("Run [bold]mthds init[/bold] first to create a manifest.")
        raise typer.Exit(code=1)

    # Parse existing manifest
    content = manifest_path.read_text(encoding="utf-8")
    try:
        manifest = parse_methods_toml(content)
    except ManifestError as exc:
        console.print(f"[red]Could not parse {MANIFEST_FILENAME}: {escape(exc.message)}[/red]")
        raise typer.Exit(code=1) from exc

    # Auto-derive alias if not provided
    if alias is None:
        alias = derive_alias_from_address(address)
        console.print(f"[dim]Auto-derived alias: {escape(alias)}[/dim]")

    # Check alias uniqueness
    existing_aliases = {dep.alias for dep in manifest.dependencies}
    if alias in existing_aliases:
        console.print(f"[red]Dependency alias '{escape(alias)}' already exists in {MANIFEST_FILENAME}.[/red]")
        raise typer.Exit(code=1)

    # Create and validate the dependency
    try:
        dep = PackageDependency(
            address=address,
            version=version,
            alias=alias,
            path=path,
        )
    except ValidationError as exc:
        console.print(f"[red]Invalid dependency: {escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc

    # Add to manifest and write back
    manifest.dependencies.append(dep)
    toml_content = serialize_manifest_to_toml(manifest)
    manifest_path.write_text(toml_content, encoding="utf-8")

    path_info = f" (path: {path})" if path else ""
    console.print(f"[green]Added dependency '{escape(alias)}' -> {escape(address)} @ {escape(version)}{escape(path_info)}[/green]")
