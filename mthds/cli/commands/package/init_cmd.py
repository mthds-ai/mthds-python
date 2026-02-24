from pathlib import Path

import typer

from mthds.cli._console import get_console
from mthds.package.discovery import MANIFEST_FILENAME
from mthds.package.manifest.parser import serialize_manifest_to_toml
from mthds.package.manifest.schema import MthdsPackageManifest


def do_init(force: bool = False, directory: str | None = None) -> None:
    """Create a bare METHODS.toml skeleton in the target directory.

    Args:
        force: If True, overwrite an existing METHODS.toml
        directory: Target package directory (defaults to current directory)
    """
    console = get_console()
    cwd = Path(directory).resolve() if directory else Path.cwd()
    manifest_path = cwd / MANIFEST_FILENAME

    # Check if manifest already exists
    if manifest_path.exists() and not force:
        console.print(f"[red]METHODS.toml already exists at {manifest_path}[/red]")
        console.print("Use --force to overwrite.")
        raise typer.Exit(code=1)

    # Generate manifest with placeholder values
    dir_name = cwd.name.replace("-", "_").replace(" ", "_").lower()
    manifest = MthdsPackageManifest(
        address=f"example.com/yourorg/{dir_name}",
        version="0.1.0",
        description=f"MTHDS package for {dir_name}",
    )

    # Serialize and write
    toml_content = serialize_manifest_to_toml(manifest)
    manifest_path.write_text(toml_content, encoding="utf-8")

    console.print(f"[green]Created {MANIFEST_FILENAME}[/green]")
    console.print(f"\n[dim]Edit {MANIFEST_FILENAME} to set the correct address, exports, and dependencies.[/dim]")
