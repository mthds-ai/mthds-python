from pathlib import Path

import typer

from mthds.cli._console import get_console
from mthds.packages.discovery import MANIFEST_FILENAME
from mthds.packages.manifest import MthdsPackageManifest
from mthds.packages.manifest_parser import serialize_manifest_to_toml


def do_init(force: bool = False) -> None:
    """Create a bare METHODS.toml skeleton in the current directory.

    Args:
        force: If True, overwrite an existing METHODS.toml
    """
    console = get_console()
    cwd = Path.cwd()
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
